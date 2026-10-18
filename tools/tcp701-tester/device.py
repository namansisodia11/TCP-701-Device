"""Async TCP link to a TCP-701 with full traffic logging and a server-side access-control engine.

Two ways to reach the device:
  * listen mode  - we are the SERVER; the device (work mode TCP Client) connects in to us.
                   This is the production topology: device Target IP = this PC, Target port = 8888.
  * client mode  - we connect to the device (factory default: device is TCP Server on :8887)
Every byte in either direction is logged to logs/session-*.jsonl and pushed to subscribers.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

import protocol as p

Emit = Callable[[dict], Awaitable[None]]

# Commands the device sends on its own, and the reply we send if auto-reply is on.
# Reply Type follows the spec examples (0109 host reply uses Type 00, others 02).
AUTO_ACK_TYPE = {0x0101: p.TYPE_RESP, 0x0109: p.TYPE_REQ, 0x0214: p.TYPE_RESP,
                 0x0210: p.TYPE_RESP, 0x0211: p.TYPE_RESP, 0x0505: p.TYPE_RESP}


class DeviceLink:
    def __init__(self, emit: Emit, log_dir: Path) -> None:
        self.emit = emit
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / f"session-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
        self.history: list[dict] = []
        self.seq = 0

        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.read_task: asyncio.Task | None = None
        self.server: asyncio.AbstractServer | None = None
        self.listen_port: int | None = None
        self.peer = ""
        self.mode = "idle"  # idle | client | listen
        self.pending: dict[int, list[asyncio.Future]] = {}

        self.header_serial = 1  # value put in the Serial field of frames we send
        self.req_type = p.TYPE_REQ_NOREPLY  # spec examples use Type 01 for requests
        self.device_sn: str | None = None
        # Transport as seen on the real device: frames written as ASCII hex text, with an
        # 8-byte ID block after the head byte. Both are auto-detected from the device's frames.
        self.wire_mode = "auto"      # auto | ascii | binary  (what we SEND; auto = follow device, default ascii)
        self.prefix_mode = "echo"    # echo (copy device's ID block) | none | ff8
        self.adopt_serial = True     # use the device's serial in frames we send
        self.last_prefix = b""
        self.decoder = p.WireDecoder()
        self.first_rx = asyncio.Event()
        # Auto-acknowledgements for device-initiated frames.
        self.auto = {"0101": True, "0109": True, "0214": True,
                     # off: the device never accepts our batch ack; for 0505 it re-sends the batch at once
                     # on every ack -> endless loop that made the device reconnect (2026-10-03)
                     "batch": False,
                     # how the batch ack is built (vendor 2026-10-09: reply command must be 0x38, not 0x88)
                     "batch_ack": "cmd0038",
                     "0108": "off"}  # off | open | deny
        # Server-side access decisions for 0215 real-time verification requests.
        self.access = {
            "policy": "rules",    # manual | allow | deny | rules  (rules = auto-allow valid QR only)
            "grant": "both",      # how "allow" is sent: status | 0201 | both
            "allow_list": [],     # card hex (8 chars) / PIN (decimal) / QR card IDs allowed by "rules"
            "qr_key": "",         # 32 hex chars - used to decrypt raw QR text forwarded by the device
            "qr_key_format": "raw16",
            "door": 1,
            "unlock_seconds": 5,  # 0201 seconds on grant = how long the door opens; 0 = device default (0203)
            "qr_require_list": False,  # QR must ALSO be in allow_list (otherwise crypto+time checks suffice)
            # online deny gives only the 1 scan beep (2026-10-03) -> send 0102 so the member hears a refusal
            "deny_beeps": 0,      # 0 = off, 1-3 = 0102 beep count after a deny
        }
        self.pending_access: dict[int, dict] = {}
        # Remembered across restarts so the first requests after a reconnect use the right format.
        self.state_path = log_dir.parent / "state.json"
        self._load_state()

    # ------------------------------------------------------------------ status
    @property
    def connected(self) -> bool:
        return self.writer is not None and not self.writer.is_closing()

    def status(self) -> dict:
        return dict(connected=self.connected, mode=self.mode, peer=self.peer,
                    listen_port=self.listen_port, wire=self.tx_wire(), wire_mode=self.wire_mode,
                    rx_wire=self.decoder.wire, prefix_mode=self.prefix_mode,
                    prefix=self.out_prefix().hex().upper(), adopt_serial=self.adopt_serial,
                    header_serial=f"{self.header_serial:08X}", req_type=self.req_type,
                    device_sn=self.device_sn, auto=self.auto, access=self.access,
                    pending_access=list(self.pending_access.values()),
                    log_file=self.log_path.name)

    def tx_wire(self) -> str:
        if self.wire_mode != "auto":
            return self.wire_mode
        return self.decoder.detected or "ascii"  # real device uses ASCII

    def _load_state(self) -> None:
        try:
            st = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.header_serial = int(st.get("header_serial", "00000001"), 16)
        self.last_prefix = bytes.fromhex(st.get("prefix", ""))
        self.device_sn = st.get("device_sn") or None
        if self.device_sn in ("FFFFFFFF", "00000000"):
            self.device_sn = None
        for k in ("qr_key", "qr_key_format"):
            if st.get(k):
                self.access[k] = st[k]
        if "unlock_seconds" in st:
            self.access["unlock_seconds"] = int(st["unlock_seconds"])
        for k in ("policy", "grant", "allow_list", "deny_beeps"):
            if k in st:
                self.access[k] = st[k]

    def save_state(self) -> None:
        st = dict(header_serial=f"{self.header_serial:08X}", prefix=self.last_prefix.hex().upper(),
                  device_sn=self.device_sn or "", qr_key=self.access["qr_key"],
                  qr_key_format=self.access["qr_key_format"],
                  unlock_seconds=int(self.access["unlock_seconds"]),
                  policy=self.access["policy"], grant=self.access["grant"],
                  allow_list=list(self.access["allow_list"]),
                  deny_beeps=int(self.access.get("deny_beeps", 0)))
        try:
            self.state_path.write_text(json.dumps(st, indent=2), encoding="utf-8")
        except OSError:
            pass

    def out_prefix(self) -> bytes:
        return {"none": b"", "ff8": b"\xff" * p.PREFIX_LEN}.get(self.prefix_mode, self.last_prefix)

    def build(self, cmd: int, data: bytes = b"", serial: int | None = None, typ: int | None = None,
              status: int = 0, **kw) -> bytes:
        return p.build(cmd, data, self.header_serial if serial is None else serial,
                       self.req_type if typ is None else typ, status, prefix=self.out_prefix(), **kw)

    # ------------------------------------------------------------------ logging
    async def _record(self, kind: str, **fields) -> dict:
        self.seq += 1
        entry = dict(id=self.seq, ts=time.time(),
                     time=datetime.now().strftime("%H:%M:%S.%f")[:-3], kind=kind, **fields)
        self.history.append(entry)
        if len(self.history) > 5000:
            del self.history[:1000]
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        await self.emit({"event": "entry", "entry": entry})
        return entry

    async def info(self, text: str) -> None:
        await self._record("info", text=text)

    async def _record_frame(self, direction: str, f: p.Frame, note: str = "", wire: str = "") -> dict:
        return await self._record(
            "frame", dir=direction, hex=f.raw.hex().upper(), head=f"{f.head:02X}",
            cmd=f"{f.cmd:04X}", cmd_name=f.cmd_name, type=f.type,
            type_name=p.TYPE_NAMES.get(f.type, f"{f.type:02X}"), status=f.status,
            serial=f"{f.serial:08X}", length=f.length, data=f.data.hex().upper(),
            ok=f.ok, desc=p.describe(f), fields=p.frame_fields(f), note=note,
            wire=wire or self.tx_wire(), id_block=f.prefix.hex().upper())

    async def _status_changed(self) -> None:
        await self.emit({"event": "status", "status": self.status()})

    # ------------------------------------------------------------------ connect
    async def connect(self, host: str, port: int, timeout: float = 5.0) -> None:
        await self.disconnect()
        await self.info(f"connecting to {host}:{port} …")
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        except Exception as e:
            await self.info(f"connect failed: {e!r}")
            await self._status_changed()
            raise
        self.mode = "client"
        await self._attach(reader, writer)

    async def listen(self, port: int) -> None:
        await self.disconnect()

        async def on_client(reader, writer):
            if self.connected:  # keep only the newest device connection
                await self.info("new inbound connection replaces the previous one")
                await self._detach()
            await self._attach(reader, writer)
            asyncio.create_task(self.identify())

        self.server = await asyncio.start_server(on_client, "0.0.0.0", port)
        self.mode = "listen"
        self.listen_port = port
        await self.info(f"SERVER listening on 0.0.0.0:{port} — waiting for the device (TCP Client mode) to connect")
        await self._status_changed()

    async def _attach(self, reader, writer) -> None:
        self.reader, self.writer = reader, writer
        self.decoder = p.WireDecoder()
        self.first_rx = asyncio.Event()
        host, port = writer.get_extra_info("peername")[:2]
        self.peer = f"{host}:{port}"
        await self.info(f"device connected from {self.peer}" if self.mode == "listen" else f"connected: {self.peer}")
        self.read_task = asyncio.create_task(self._read_loop())
        await self._status_changed()

    async def _detach(self) -> None:
        if self.read_task and self.read_task is not asyncio.current_task():
            self.read_task.cancel()
        self.read_task = None
        if self.writer:
            try:
                self.writer.close()
            except Exception:
                pass
        self.reader = self.writer = None
        self.peer = ""
        for futs in self.pending.values():
            for fut in futs:
                if not fut.done():
                    fut.cancel()
        self.pending.clear()
        self.pending_access.clear()

    async def disconnect(self) -> None:
        was = self.connected or self.server is not None
        await self._detach()
        if self.server:
            self.server.close()
            self.server = None
        self.mode = "idle"
        self.listen_port = None
        if was:
            await self.info("disconnected / stopped listening")
        await self._status_changed()

    # ------------------------------------------------------------------ reading
    async def _read_loop(self) -> None:
        parser = self.decoder
        try:
            while True:
                chunk = await self.reader.read(4096)
                if not chunk:
                    await self.info("device closed the connection")
                    break
                was = parser.detected
                items = parser.feed(chunk)
                if was is None and parser.detected:
                    await self.info(f"device sends {parser.detected.upper()} frames; we answer in "
                                    f"{self.tx_wire().upper()}")
                    await self._status_changed()
                for item in items:
                    if isinstance(item, bytes):
                        await self._record("junk", dir="rx", hex=item.hex().upper(),
                                           text=f"{len(item)} byte(s) outside any frame")
                    else:
                        entry = await self._record_frame("rx", item, wire=parser.wire)
                        await self._learn(item)
                        await self._on_frame(item, entry)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self.info(f"read error: {e!r}")
        finally:
            rest = parser.flush()
            if rest:
                await self._record("junk", dir="rx", hex=rest.hex().upper(),
                                   text="incomplete frame left in buffer")
            if self.read_task is asyncio.current_task():
                await self._detach()
                if self.mode == "client":
                    self.mode = "idle"
                await self._status_changed()

    async def _learn(self, f: p.Frame) -> None:
        """Adopt the device's ID block and serial from its own (valid) frames."""
        if not (f.from_device and f.ok):
            return
        changed = False
        if f.prefix != self.last_prefix:
            self.last_prefix, changed = f.prefix, True
        if self.adopt_serial and f.serial not in (0, 0xFFFFFFFF) and f.serial != self.header_serial:
            self.header_serial, changed = f.serial, True
            await self.info(f"using device serial {f.serial:08X} in frames we send")
        if not self.device_sn and f.serial not in (0, 0xFFFFFFFF):
            self.device_sn, changed = f"{f.serial:08X}", True
        self.first_rx.set()
        if changed:
            self.save_state()
            await self._status_changed()

    async def _on_frame(self, f: p.Frame, entry: dict) -> None:
        # 1) resolve a waiting request (any device frame with the same cmd that is not an event)
        if f.from_device and f.type != p.TYPE_EVENT:
            futs = self.pending.get(f.cmd)
            while futs:
                fut = futs.pop(0)
                if not fut.done():
                    fut.set_result(f)
                    if f.cmd in (0x0210, 0x0211, 0x0505) and self.auto["batch"]:
                        await self._auto_reply(f)  # the first batch is the reply to our request but needs an ack too
                    return  # it was a reply to us, not an unsolicited frame
        # 2) unsolicited frame -> access decision / auto reply
        if f.cmd == 0x0215 and f.from_device:
            await self._on_access_request(f, entry)
        else:
            await self._auto_reply(f)

    async def _auto_reply(self, f: p.Frame) -> None:
        a, cmd = self.auto, f.cmd
        if cmd == 0x0101 and a["0101"]:
            await self.send(self.build(0x0101, b"", f.serial, AUTO_ACK_TYPE[0x0101]), "auto-ack heartbeat")
        elif cmd == 0x0109 and a["0109"]:
            await self.send(self.build(0x0109, b"", f.serial, AUTO_ACK_TYPE[0x0109]), "auto-ack door sensor")
        elif cmd == 0x0214 and a["0214"]:
            await self.send(self.build(0x0214, b"", f.serial, AUTO_ACK_TYPE[0x0214]), "auto-ack realtime log")
        elif cmd in (0x0210, 0x0211, 0x0505) and a["batch"]:
            await self.send(self._batch_ack(cmd, f.serial), f"auto-ack batch ({a['batch_ack']})")
        elif cmd == 0x0108 and a["0108"] in ("open", "deny"):
            d = b"\x01" if a["0108"] == "open" else b"\x00"
            await self.send(self.build(0x0108, d, f.serial, p.TYPE_RESP), f"auto-reply doorbell: {a['0108']}")

    def _batch_ack(self, cmd: int, serial: int) -> bytes:
        """Ack for a batch of 8 records/16 users. The vendor says the reply 'command' must be 0x38 (not 0x88);
        which field that is isn't clear, so several readings can be tried from the UI."""
        v, typ = self.auto["batch_ack"], AUTO_ACK_TYPE[cmd]
        if v == "cmd0038":
            return self.build(0x0038, b"", serial, typ)
        if v == "cmd0238":
            return self.build(0x0238, b"", serial, typ)
        if v == "status38":
            return self.build(cmd, b"", serial, typ, status=0x38)
        if v == "data38":
            return self.build(cmd, b"8", serial, typ)
        if v == "type38":
            return self.build(cmd, b"", serial, 0x38)
        return self.build(cmd, b"", serial, typ)  # "plain": the old ack, which was never accepted

    # ------------------------------------------------------------------ access control (0215)
    def evaluate(self, data: bytes) -> dict:
        """Decode a 0215 payload and apply the 'rules' policy. Returns summary + rule verdict."""
        d, acc = data, self.access
        allow = {s.strip().upper() for s in acc["allow_list"] if s.strip()}
        res: dict = {"decoded": p.decode_0215(d), "kind": "unknown", "credential": "", "reasons": []}
        ok = False
        text = d[1:].decode("latin-1").strip() if d[:1] == b"\x50" else ""
        if text and text.isprintable() and text.upper() in allow:
            # plain-text token QR (e.g. "GW:1:8F3A2C") listed in the allow list; checked first so
            # short texts aren't mistaken for the card / 16-byte formats below
            res.update(kind="QR (text)", credential=text, qr_text=text)
            ok = True
        elif len(d) == 2:
            res.update(kind="exit button", credential="button")
            ok = True
        elif len(d) == 5:
            if d[0] in (0x20, 0x21):
                pin = str(int.from_bytes(d[1:5], "big"))
                res.update(kind="PIN", credential=pin)
                ok = pin in allow
            else:
                card = d[1:5].hex().upper()
                res.update(kind="card", credential=card)
                ok = card in allow
            if not ok:
                res["reasons"].append(f"{res['credential']} not in allow list")
        elif len(d) == 16 and d[0] in (0x50, 0x51):
            val = d[4:8].hex().upper()
            start, end = int.from_bytes(d[8:12], "big"), int.from_bytes(d[12:16], "big")
            res.update(kind="QR (device-decoded)", credential=val)
            now = time.time()
            if p.ts_text(start) != "?" and now < start:
                res["reasons"].append("QR not valid yet")
            if p.ts_text(end) != "?" and now > end:
                res["reasons"].append("QR expired")
            if acc["qr_require_list"] and val not in allow:
                res["reasons"].append(f"{val} not in allow list")
            ok = not res["reasons"]
        else:
            # Probably the raw QR content forwarded as-is: try to decrypt with our key.
            res["kind"] = "QR (raw content)"
            body = d[1:] if d[:1] == b"\x50" else d
            if not acc["qr_key"]:
                res["reasons"].append("no QR key configured to decrypt")
            else:
                try:
                    key = p.qr_key_bytes(acc["qr_key"], acc["qr_key_format"])
                    # real device: 0x50 ('P' = QR type) + the scanned QR text as-is
                    content = body.decode("latin-1")
                    res["qr_text"] = content
                    info = p.qr_decode_content(content, key)
                    res["qr"] = info
                    res["credential"] = info.get("card_id", "")
                    sn = int(self.device_sn, 16) if self.device_sn else None
                    res["reasons"] += p.qr_check(info, sn, int(acc["door"]))
                    if acc["qr_require_list"] and res["credential"] not in allow:
                        res["reasons"].append(f"{res['credential']} not in allow list")
                except Exception as e:
                    res["reasons"].append(f"decrypt failed: {e}")
            ok = not res["reasons"]
        res["rule_verdict"] = "allow" if ok else "deny"
        return res

    async def _on_access_request(self, f: p.Frame, entry: dict) -> None:
        ev = self.evaluate(f.data)
        policy = self.access["policy"]
        item = dict(id=entry["id"], serial=f.serial, time=entry["time"], kind=ev["kind"],
                    credential=ev["credential"], decoded=ev["decoded"], reasons=ev["reasons"],
                    rule_verdict=ev["rule_verdict"], qr=ev.get("qr"))
        await self._record("access", text=f"ACCESS REQUEST #{entry['id']}: {ev['kind']} {ev['credential']} "
                                          f"→ rules say {ev['rule_verdict'].upper()}"
                                          + (f" ({'; '.join(ev['reasons'])})" if ev["reasons"] else ""),
                           request=item)
        if policy == "manual":
            self.pending_access[entry["id"]] = item
            await self.emit({"event": "access_pending", "item": item})
            await self._status_changed()
            return
        allow = {"allow": True, "deny": False}.get(policy, ev["rule_verdict"] == "allow")
        await self.answer_access(f.serial, allow, f"auto ({policy})")

    async def answer_access(self, serial: int, allow: bool, why: str, req_id: int | None = None) -> None:
        grant = self.access["grant"]
        tag = f"{why}: {'ALLOW' if allow else 'DENY'}"
        if req_id is not None:
            self.pending_access.pop(req_id, None)
        if not allow:
            await self.send(self.build(0x0215, b"", serial, p.TYPE_RESP, 0x01), f"{tag} (0215 status 01)")
            beeps = int(self.access.get("deny_beeps", 0))
            if 1 <= beeps <= 3:
                await asyncio.sleep(0.3)  # same gap as 0201 after a 0215 reply
                await self.send(self.build(0x0102, bytes([beeps])), f"{tag} (0102 beep x{beeps})")
        else:
            if grant in ("status", "both"):
                await self.send(self.build(0x0215, b"", serial, p.TYPE_RESP, 0x00), f"{tag} (0215 status 00)")
            if grant in ("0201", "both"):
                if grant == "both":
                    # the device ignored a 0201 sent in the same instant as the 0215 reply (2026-09-30)
                    await asyncio.sleep(0.3)
                secs = int(self.access.get("unlock_seconds", 5)) & 0xFF
                await self.send(self.build(0x0201, bytes([secs])), f"{tag} (0201 unlock {secs}s)")
        await self._status_changed()

    # ------------------------------------------------------------------ writing
    async def send(self, raw: bytes, note: str = "") -> None:
        if not self.connected:
            raise ConnectionError("device not connected")
        wire = self.tx_wire()
        self.writer.write(raw.hex().upper().encode() if wire == "ascii" else raw)
        await self.writer.drain()
        parser = p.FrameParser()
        for item in parser.feed(raw):
            if isinstance(item, p.Frame):
                await self._record_frame("tx", item, note, wire)
            else:
                await self._record("junk", dir="tx", hex=item.hex().upper(), text="bytes outside any frame")
        leftover = parser.flush()
        if leftover:
            await self._record("junk", dir="tx", hex=leftover.hex().upper(), text="incomplete/short frame")

    async def request(self, cmd: int, data: bytes = b"", timeout: float = 3.0,
                      typ: int | None = None, note: str = "") -> p.Frame | None:
        raw = self.build(cmd, data, typ=typ)
        fut = asyncio.get_running_loop().create_future()
        self.pending.setdefault(cmd, []).append(fut)
        await self.send(raw, note)
        try:
            return await asyncio.wait_for(fut, timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            await self.info(f"no reply to {p.CMD_NAMES.get(cmd, hex(cmd))} within {timeout:.0f}s")
            return None
        finally:
            if fut in self.pending.get(cmd, []):
                self.pending[cmd].remove(fut)

    async def download_records(self) -> dict:
        """Read every stored record one by one with 0213 (index from 0; an all-FF record = end).

        0211 can't be used: the device sends the first batch of 8 and never accepts our batch ack."""
        records: list[str] = []
        misses = 0
        while len(records) < 0x10000 and misses < 3:
            f = await self.request(0x0213, len(records).to_bytes(2, "big"), timeout=2.0, note="download records")
            if f is None:
                misses += 1
                continue
            misses = 0
            if not f.data or f.data[:4] == b"\xff\xff\xff\xff":
                break
            records.append(f.data.hex().upper())
        path = self.log_dir / f"records-{datetime.now():%Y%m%d-%H%M%S}.json"
        path.write_text(json.dumps(records, indent=0), encoding="utf-8")
        complete = misses < 3
        await self.info(f"downloaded {len(records)} stored records -> {path.name}"
                        + ("" if complete else " (STOPPED: device stopped answering)"))
        return dict(count=len(records), file=path.name, complete=complete,
                    records=[dict(hex=r, **p.decode_log(bytes.fromhex(r))) for r in records])

    async def identify(self) -> None:
        """Connect-time identification: serial, version, counts.

        Waits briefly for the device's first frame so we know its wire format, ID block and serial."""
        try:
            await asyncio.wait_for(self.first_rx.wait(), 3)
        except asyncio.TimeoutError:
            await self.info(f"device sent nothing within 3 s; sending requests in {self.tx_wire().upper()}")
        f = await self.request(0x0001, note="auto on connect")
        # FFFFFFFF/00000000 = serial lost (incident 2026-10-03): keep the last real SN for QR checks
        if f and len(f.data) == 4 and f.data.hex().upper() not in ("FFFFFFFF", "00000000"):
            self.device_sn = f.data.hex().upper()
            await self._status_changed()
        await self.request(0x0002, note="auto on connect")
        await self.request(0x0202, note="auto on connect")
