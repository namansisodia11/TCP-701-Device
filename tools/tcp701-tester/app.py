"""TCP-701 local test dashboard.

    python app.py                 # http://localhost:8000 (also reachable from phone on the LAN)
    python app.py --port 8080
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import re
import socket
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import protocol as p
from device import DeviceLink

ROOT = Path(__file__).parent
LISTEN_ON_START: int | None = None  # set by --listen


@asynccontextmanager
async def lifespan(_app):
    if LISTEN_ON_START:
        await link.listen(LISTEN_ON_START)
    yield
    await link.disconnect()


app = FastAPI(title="TCP-701 tester", lifespan=lifespan)
clients: set[WebSocket] = set()


async def broadcast(msg: dict) -> None:
    dead = []
    for ws in list(clients):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


link = DeviceLink(broadcast, ROOT / "logs")


def parse_hex(s: str) -> bytes:
    s = re.sub(r"[\s,:]|0x", "", s or "", flags=re.I)
    try:
        return bytes.fromhex(s)
    except ValueError:
        raise HTTPException(400, f"invalid hex: {s!r}")


def frame_json(f: p.Frame | None) -> dict | None:
    if f is None:
        return None
    return dict(cmd=f"{f.cmd:04X}", type=f.type, status=f.status, data=f.data.hex().upper(),
                ok=f.ok, desc=p.describe(f))


# ---------------------------------------------------------------- models
class ConnectReq(BaseModel):
    host: str = "192.168.3.7"
    port: int = 8887
    identify: bool = True


class ListenReq(BaseModel):
    port: int = 8888


class CmdReq(BaseModel):
    cmd: str  # hex, e.g. "0001"
    data: str = ""  # hex
    type: int | None = None
    timeout: float = 3.0


class RawReq(BaseModel):
    hex: str
    fix_checksum: bool = True


class BuildReq(BaseModel):
    head: str = "FA"
    serial: str | None = None
    cmd: str
    type: int = 1
    status: int = 0
    data: str = ""
    bad_checksum: bool = False


class SettingsReq(BaseModel):
    header_serial: str | None = None
    req_type: int | None = None
    auto: dict | None = None
    access: dict | None = None
    wire_mode: str | None = None    # auto | ascii | binary
    prefix_mode: str | None = None  # echo | none | ff8
    adopt_serial: bool | None = None


class ProbeReq(BaseModel):
    host: str = "192.168.3.7"
    port: int = 8887
    scan_subnet: bool = False


class NoteReq(BaseModel):
    text: str


# ---------------------------------------------------------------- routes
@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await ws.send_json({"event": "history", "entries": link.history[-2000:]})
    await ws.send_json({"event": "status", "status": link.status()})
    try:
        while True:
            await ws.receive_text()  # keepalive; UI uses REST for actions
    except WebSocketDisconnect:
        clients.discard(ws)


@app.get("/api/status")
async def status():
    return link.status()


@app.post("/api/connect")
async def connect(req: ConnectReq):
    try:
        await link.connect(req.host, req.port)
    except Exception as e:
        raise HTTPException(502, f"connect failed: {e}")
    if req.identify:
        asyncio.create_task(link.identify())
    return link.status()


@app.post("/api/listen")
async def listen(req: ListenReq):
    try:
        await link.listen(req.port)
    except OSError as e:
        raise HTTPException(500, f"cannot listen on {req.port}: {e}")
    return link.status()


@app.post("/api/disconnect")
async def disconnect():
    await link.disconnect()
    return link.status()


@app.post("/api/cmd")
async def cmd(req: CmdReq):
    """Send a command and wait for its reply."""
    if not link.connected:
        raise HTTPException(409, "not connected")
    cmd = int(req.cmd, 16)
    # erasing all logs (0212) took ~15 s on the real device; erasing all users (0503) is likely slow too
    timeout = max(req.timeout, 30.0) if cmd in (0x0212, 0x0503) else req.timeout
    f = await link.request(cmd, parse_hex(req.data), timeout, req.type)
    return {"reply": frame_json(f)}


class SerialReq(BaseModel):
    new_serial: str = "BB900021"  # 8 hex chars
    current_serial: str = "FFFFFFFF"  # serial the device has now (header serial)


@app.post("/api/set_serial")
async def set_serial(req: SerialReq):
    """Vendor command to rewrite the machine number (answer of 2026-10-09):
    FA + FF*8 + ck + len 0008 + serial + cmd 0000 + type 01 + status 00 + AFFFAC88 + new serial."""
    if not link.connected:
        raise HTTPException(409, "not connected")
    try:
        new, cur = bytes.fromhex(req.new_serial), int(req.current_serial, 16)
    except ValueError:
        raise HTTPException(400, "serials must be 8 hex characters")
    if len(new) != 4:
        raise HTTPException(400, "new serial must be 8 hex characters")
    data = p.build(0x0000, bytes.fromhex("AFFFAC88") + new, cur, 1, 0, prefix=bytes([0xFF]) * p.PREFIX_LEN)
    await link.send(data, "vendor: set machine number")
    return {"sent": data.hex().upper()}


@app.post("/api/raw")
async def raw(req: RawReq):
    """Send arbitrary bytes; optionally recompute length+checksum first."""
    if not link.connected:
        raise HTTPException(409, "not connected")
    data = parse_hex(req.hex)
    if req.fix_checksum:
        # typed frame includes the 8-byte ID block if it matches the one we are using
        pre = link.out_prefix()
        prefix_len = len(pre) if pre and data[1:1 + len(pre)] == pre else 0
        try:
            data = p.fix_checksum(data, prefix_len)
        except ValueError as e:
            raise HTTPException(400, str(e))
    await link.send(data, "raw" + (" (checksum fixed)" if req.fix_checksum else " (as typed)"))
    return {"sent": data.hex().upper()}


@app.post("/api/build")
async def build(req: BuildReq):
    """Build a frame from fields and send it (supports deliberately bad checksum)."""
    if not link.connected:
        raise HTTPException(409, "not connected")
    serial = int(req.serial, 16) if req.serial else link.header_serial
    frame = p.build(int(req.cmd, 16), parse_hex(req.data), serial, req.type, req.status,
                    int(req.head, 16), req.bad_checksum, prefix=link.out_prefix())
    await link.send(frame, "built" + (" with BAD checksum" if req.bad_checksum else ""))
    return {"sent": frame.hex().upper()}


@app.post("/api/settings")
async def settings(req: SettingsReq):
    if req.header_serial is not None:
        link.header_serial = int(req.header_serial, 16)
    if req.req_type is not None:
        link.req_type = req.req_type
    if req.auto:
        link.auto.update({k: v for k, v in req.auto.items() if k in link.auto})
    if req.access:
        link.access.update({k: v for k, v in req.access.items() if k in link.access})
        link.save_state()
    if req.wire_mode in ("auto", "ascii", "binary"):
        link.wire_mode = req.wire_mode
    if req.prefix_mode in ("echo", "none", "ff8"):
        link.prefix_mode = req.prefix_mode
    if req.adopt_serial is not None:
        link.adopt_serial = req.adopt_serial
    await broadcast({"event": "status", "status": link.status()})
    return link.status()


@app.post("/api/note")
async def note(req: NoteReq):
    """Free-text note into the session log (test observations)."""
    await link._record("note", text=req.text)
    return {"ok": True}


@app.post("/api/probe")
async def probe(req: ProbeReq):
    """Check whether host:port accepts TCP; optionally scan the /24 for the port."""
    async def try_one(host: str) -> bool:
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection(host, req.port), 0.8)
            w.close()
            return True
        except Exception:
            return False

    if not req.scan_subnet:
        return {"found": [req.host] if await try_one(req.host) else []}
    net = ipaddress.ip_network(f"{req.host}/24", strict=False)
    hosts = [str(h) for h in net.hosts()]
    found: list[str] = []
    sem = asyncio.Semaphore(64)

    async def check(h):
        async with sem:
            if await try_one(h):
                found.append(h)

    await asyncio.gather(*(check(h) for h in hosts))
    return {"found": sorted(found, key=lambda h: ipaddress.ip_address(h))}


@app.post("/api/records/download")
async def records_download():
    """Read all stored door records one by one (0213) and save them to logs/records-*.json."""
    if not link.connected:
        raise HTTPException(409, "not connected")
    return await link.download_records()


@app.get("/api/log/export")
async def export_log():
    if not link.log_path.exists():
        raise HTTPException(404, "no log yet")
    return FileResponse(link.log_path, filename=link.log_path.name, media_type="application/x-ndjson")


@app.get("/api/commands")
async def commands():
    return {f"{k:04X}": v for k, v in p.CMD_NAMES.items()}


@app.get("/api/netinfo")
async def netinfo():
    """This PC's IPv4 addresses — one of these goes into the device's Target IP."""
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    ips.discard("127.0.0.1")
    return {"ips": sorted(ips, key=lambda h: ipaddress.ip_address(h)), "listen_port": link.listen_port}


# ---------------------------------------------------------------- access control
class AnswerReq(BaseModel):
    id: int
    allow: bool


@app.post("/api/access/answer")
async def access_answer(req: AnswerReq):
    item = link.pending_access.get(req.id)
    if not item:
        raise HTTPException(404, "request no longer pending")
    await link.answer_access(item["serial"], req.allow, "manual", req.id)
    return {"ok": True}


class AccessTestReq(BaseModel):
    allow: bool


@app.post("/api/access/unlock")
async def access_unlock(req: AccessTestReq):
    """Send a grant/deny for the device's most recent request without a pending id (serial from header)."""
    await link.answer_access(link.header_serial, req.allow, "manual (no request id)")
    return {"ok": True}


# ---------------------------------------------------------------- QR
class QrReq(BaseModel):
    key: str
    key_format: str = "raw16"       # raw16 | ascii32
    content_format: str = "hex_text"  # hex_text | binary
    card_id: str = "00000001"       # hex
    device_sn: str = "00000001"     # hex
    doors: list[int] = [1]
    start: int                      # unix ts
    duration_min: int = 5
    validity: int                   # unix ts
    limit: int = 0
    card_type: int = 1
    ladder_uid: str = "FFF1"
    bad_crc: bool = False
    encrypt_key: str | None = None  # use a different key to encrypt (wrong-key test)


def _qr_svg(qr) -> str:
    # viewBox lets the UI resize the SVG via CSS (scale instead of crop)
    w, h = qr.symbol_size(scale=8, border=4)
    return qr.svg_inline(scale=8, border=4, dark="#000", light="#fff").replace(
        "<svg ", f'<svg viewBox="0 0 {w} {h}" shape-rendering="crispEdges" ', 1)


class QrTextReq(BaseModel):
    text: str


@app.post("/api/qr/text")
async def qr_text(req: QrTextReq):
    """Plain (unencrypted) QR from any text: for size/scan tests and short-token designs."""
    import segno

    if not req.text:
        raise HTTPException(400, "empty text")
    qr = segno.make(req.text, error="l", micro=False)
    return dict(content=req.text, chars=len(req.text), qr_version=qr.version,
                modules=qr.symbol_size(scale=1, border=0)[0], svg=_qr_svg(qr))


@app.post("/api/qr/generate")
async def qr_generate(req: QrReq):
    import segno

    try:
        plain = p.qr_plain(int(req.card_id, 16), int(req.device_sn, 16), req.doors, req.start,
                           req.duration_min, req.validity, req.limit, req.card_type,
                           int(req.ladder_uid, 16), bad_crc=req.bad_crc)
        key = p.qr_key_bytes(req.encrypt_key or req.key, req.key_format)
    except ValueError as e:
        raise HTTPException(400, str(e))
    ct, content = p.qr_encode(plain, key, req.content_format)
    qr = segno.make(content, error="l", micro=False)
    info = p.qr_parse_plain(plain)
    svg = _qr_svg(qr)
    return dict(plain=plain.hex().upper(), cipher=ct.hex().upper(),
                content=content if isinstance(content, str) else ct.hex().upper(),
                content_format=req.content_format, qr_version=qr.version,
                svg=svg,
                fields=[(n, info[n]) for n, _ in p.QR_FIELDS],
                summary=dict(doors=info["door_list"], start=info["start_text"], end=info["end_text"],
                             validity=info["validity_text"], limit=info["limit_int"], crc_ok=info["crc_ok"]))


class QrDecodeReq(BaseModel):
    content: str
    key: str
    key_format: str = "raw16"
    device_sn: str | None = None
    door: int = 1


@app.post("/api/qr/decode")
async def qr_decode(req: QrDecodeReq):
    try:
        info = p.qr_decode_content(req.content, p.qr_key_bytes(req.key, req.key_format))
    except ValueError as e:
        raise HTTPException(400, str(e))
    sn = int(req.device_sn, 16) if req.device_sn else None
    return {"info": info, "problems": p.qr_check(info, sn, req.door)}


class KeyReq(BaseModel):
    key: str
    key_format: str = "raw16"


@app.post("/api/qr/load_key")
async def qr_load_key(req: KeyReq):
    """Send 0601 with the key and remember it for server-side decryption."""
    if not link.connected:
        raise HTTPException(409, "device not connected")
    try:
        data = p.qr_key_0601_data(req.key)
    except ValueError as e:
        raise HTTPException(400, str(e))
    f = await link.request(0x0601, data, note="load QR key")
    link.access.update(qr_key=req.key.strip().upper(), qr_key_format=req.key_format)
    link.save_state()
    await broadcast({"event": "status", "status": link.status()})
    return {"reply": frame_json(f)}


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


if __name__ == "__main__":
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = reachable from phone on LAN")
    ap.add_argument("--port", type=int, default=8000, help="dashboard web port")
    ap.add_argument("--listen", type=int, default=8888,
                    help="TCP port the device (TCP Client mode) connects to; 0 = don't listen on start")
    a = ap.parse_args()
    LISTEN_ON_START = a.listen or None
    print(f"TCP-701 tester -> dashboard http://localhost:{a.port}")
    ips = [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    for ip in sorted(set(ips) - {"127.0.0.1"}):
        print(f"Phone QR page -> http://{ip}:{a.port}/static/phone.html")
    if LISTEN_ON_START:
        print(f"Device server listening on port {LISTEN_ON_START}. Set the device's Target IP to one of: "
              f"{', '.join(sorted(set(ips)))}  and Target port {LISTEN_ON_START}")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
