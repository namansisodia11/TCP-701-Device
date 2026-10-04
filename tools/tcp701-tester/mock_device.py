"""Fake TCP-701 for testing the dashboard without hardware.

    python mock_device.py --connect 127.0.0.1:8888   # TCP Client mode: connects to our server (production-like)
    python mock_device.py                            # TCP Server mode: listens on 127.0.0.1:8887
    python mock_device.py --heartbeat 10 --events 20

Wire format matches the REAL device (observed 2026-09-30): frames written as ASCII hex text,
with an 8-byte FF ID block after the head byte, serial BB900021. Use --binary / --no-id for the
plain spec format.

Behaviour (a best guess at the real device, based on the spec):
  * replies to every request with AF, same cmd, Type 02, Status 00 (+ data where known)
  * ignores frames with a bad checksum
  * sends a 0101 heartbeat every --heartbeat seconds
  * every --events seconds emits either a 0109 door event (repeated every 5 s until acked)
    or a 0215 card-swipe verification request
"""
from __future__ import annotations

import argparse
import asyncio
import random
import time
from datetime import datetime

import protocol as p

SN = 0xBB900021
QR_KEY = {"hex": ""}  # set by 0601
WIRE = {"ascii": True, "prefix": b"\xff" * p.PREFIX_LEN}


def dbuild(cmd: int, data: bytes = b"", typ: int = p.TYPE_EVENT, status: int = 0, serial: int = SN) -> bytes:
    """Frame as the device writes it (head AF + ID block)."""
    return p.build(cmd, data, serial, typ, status, head=p.HEAD_DEVICE, prefix=WIRE["prefix"])
users: list[bytes] = [p.user_record(0x36F2E63F, 11111111, 1), p.user_record(0x00BC614E, 0, 2)]
logs: list[bytes] = [bytes.fromhex("80EC0000000000000000250918140746"),
                     bytes.fromhex("10EC0000000036F2E63F250918141002")]


def log(msg: str) -> None:
    print(f"[mock {datetime.now():%H:%M:%S}] {msg}", flush=True)


def reply(f: p.Frame, data: bytes = b"", status: int = 0) -> bytes:
    return dbuild(f.cmd, data, p.TYPE_RESP, status, f.serial)


def handle(f: p.Frame) -> list[bytes]:
    c, d = f.cmd, f.data
    if c == 0x0001:
        return [reply(f, SN.to_bytes(4, "big"))]
    if c == 0x0002:
        return [reply(f, b"\x00\x03")]
    if c == 0x0202:
        return [reply(f, len(users).to_bytes(2, "big") + len(logs).to_bytes(2, "big"))]
    if c == 0x0501 and len(d) == 16:
        if any(u[:4] == d[:4] and d[:4] != b"\0\0\0\0" for u in users):
            return [reply(f, status=1)]
        users.append(d)
        return [reply(f)]
    if c == 0x0503:
        users.clear()
        return [reply(f)]
    if c in (0x0210, 0x0211):
        return [reply(f, b"".join(logs[:8]))]
    if c == 0x0212:
        logs.clear()
        return [reply(f)]
    if c == 0x0213:
        i = int.from_bytes(d[:2], "big") if len(d) >= 2 else 0
        return [reply(f, logs[i] if i < len(logs) else b"\xff" * 16)]
    if c == 0x0505:
        return [reply(f, b"".join(users[:16]))]
    if c == 0x0201:
        log("   *** door unlocked ***")
        logs.append(bytes([0x60, 0xEC]) + b"\0" * 8 + bytes.fromhex(datetime.now().strftime("%y%m%d%H%M%S")))
        return [reply(f)]
    if c == 0x0601 and len(d) == 32:
        QR_KEY["hex"] = d.decode("ascii")
        log(f"   QR key set to {QR_KEY['hex']}")
        return [reply(f)]
    if c == 0x0003:
        return [reply(f, b"\x01")]
    if c == 0x0004:
        return [reply(f, b"\x38")]
    return [reply(f)]


async def session(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, hb: float, ev: float):
    peer = writer.get_extra_info("peername")
    log(f"client connected {peer}")
    parser = p.WireDecoder()
    door_unacked = asyncio.Event()

    async def send(raw: bytes, why: str):
        writer.write(raw.hex().upper().encode() if WIRE["ascii"] else raw)
        await writer.drain()
        log(f"-> {raw.hex().upper()}  ({why})")

    async def heartbeat():
        while True:
            await asyncio.sleep(hb)
            # real device: Type 00, data = 7-byte BCD clock + 0xBB
            await send(dbuild(0x0101, p.bcd_time() + b"\xbb", p.TYPE_REQ), "heartbeat")

    async def door_repeater():
        while True:
            await door_unacked.wait()
            await send(dbuild(0x0109, b"\x01"), "door open (until acked)")
            await asyncio.sleep(5)

    def verify(data: bytes) -> bytes:
        return dbuild(0x0215, data)

    async def events():
        while True:
            await asyncio.sleep(ev)
            kind = random.choice(["door", "card", "pin", "qr16", "qrraw"])
            now = int(time.time())
            if kind == "door":
                door_unacked.set()
            elif kind == "card":
                card = random.choice([0x36F2E63F, 0x12345678])
                await send(verify(b"\x10" + card.to_bytes(4, "big")), "card swipe verify")
            elif kind == "pin":
                await send(verify(b"\x21" + (123456).to_bytes(4, "big")), "PIN verify")
            elif kind == "qr16":  # spec layout: 50, mode, sub, dtype, 4B id, 4B start, 4B end
                data = bytes([0x50, 0x02, 0x00, 0x01]) + (1).to_bytes(4, "big") \
                    + (now - 60).to_bytes(4, "big") + (now + 240).to_bytes(4, "big")
                await send(verify(data), "QR verify (16-byte form)")
            else:  # raw QR text forwarded as-is (alternative behaviour we may see)
                key_hex = QR_KEY["hex"] or "00112233445566778899AABBCCDDEEFF"
                plain = p.qr_plain(1, SN, [1], now - 60, 5, now + 86400)
                _, content = p.qr_encode(plain, p.qr_key_bytes(key_hex, "raw16"))
                await send(verify(content.encode()), "QR verify (raw hex text)")

    tasks = [asyncio.create_task(t()) for t in (heartbeat, door_repeater, events)]
    try:
        while chunk := await reader.read(4096):
            for item in parser.feed(chunk):
                if isinstance(item, bytes):
                    log(f"<- junk {item.hex().upper()}")
                    continue
                log(f"<- {item.raw.hex().upper()}  {item.cmd_name} ok={item.ok}")
                if not item.ok:
                    log("   bad checksum -> ignored")
                    continue
                if item.head == p.HEAD_HOST and item.cmd == 0x0109:
                    door_unacked.clear()
                    log("   door event acked")
                    continue
                if item.cmd == 0x0215 and item.type == p.TYPE_RESP:
                    log(f"   server says {'ALLOW -> door opens' if item.status == 0 else 'DENY'}")
                    continue
                if item.cmd in (0x0101, 0x0108) and item.type == p.TYPE_RESP:
                    continue  # host acks to our events
                for out in handle(item):
                    await send(out, "reply")
    finally:
        for t in tasks:
            t.cancel()
        writer.close()
        log("client disconnected")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8887)
    ap.add_argument("--heartbeat", type=float, default=5)
    ap.add_argument("--binary", action="store_true", help="binary frames instead of ASCII hex text")
    ap.add_argument("--no-id", action="store_true", help="omit the 8-byte ID block (plain spec layout)")
    ap.add_argument("--events", type=float, default=25)
    ap.add_argument("--connect", metavar="HOST:PORT",
                    help="act as TCP Client (like the real device in production) and connect to the server")
    a = ap.parse_args()
    WIRE["ascii"] = not a.binary
    WIRE["prefix"] = b"" if a.no_id else WIRE["prefix"]
    if a.connect:
        host, port = a.connect.rsplit(":", 1)
        log(f"mock TCP-701 in TCP Client mode -> {host}:{port} (SN {SN:08X})")
        while True:  # reconnect forever, like the real device
            try:
                reader, writer = await asyncio.open_connection(host, int(port))
                await session(reader, writer, a.heartbeat, a.events)
            except OSError as e:
                log(f"connect failed ({e}); retrying in 3 s")
            await asyncio.sleep(3)
    server = await asyncio.start_server(lambda r, w: session(r, w, a.heartbeat, a.events), a.host, a.port)
    log(f"mock TCP-701 listening on {a.host}:{a.port} (SN {SN:08X})")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
