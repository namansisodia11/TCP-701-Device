"""TCP-701 frame codec and payload encoders/decoders.

Frame layout (all big-endian, see .claude/skills/tcp701-protocol/SKILL.md §2):
    Head(1) Checksum(2) Length(2) Serial(4) Cmd(2) Type(1) Status(1) Data(N)
    checksum = sum(bytes from Length to end of Data) & 0xFFFF
"""
from __future__ import annotations

import re
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime

HEAD_HOST = 0xFA  # frames sent by us (host/server)
HEAD_DEVICE = 0xAF  # frames sent by the device
HEADER_LEN = 13

TYPE_REQ = 0x00
TYPE_REQ_NOREPLY = 0x01
TYPE_RESP = 0x02
TYPE_EVENT = 0x03
TYPE_NAMES = {0: "REQ", 1: "REQ*", 2: "RESP", 3: "EVENT"}

CMD_NAMES = {
    0x0001: "Serial / HW ID",
    0x0002: "Firmware version",
    0x0003: "OTA start/end",
    0x0004: "OTA data",
    0x0101: "Heartbeat",
    0x0102: "Beep",
    0x0103: "Sync time",
    0x0104: "Valid start time",
    0x0105: "Valid end time",
    0x0106: "Online/offline mode",
    0x0107: "Open mode",
    0x0108: "Doorbell call",
    0x0109: "Door sensor",
    0x0201: "Unlock",
    0x0202: "User/record counts",
    0x0203: "Relay delay",
    0x0204: "Time-limit switch",
    0x0205: "Heartbeat interval",
    0x0210: "Read new logs",
    0x0211: "Read all logs",
    0x0212: "Format logs",
    0x0213: "Read single log",
    0x0214: "Real-time log",
    0x0215: "Real-time verify",
    0x0501: "Add user",
    0x0502: "Delete user",
    0x0503: "Format users",
    0x0504: "Batch add users",
    0x0505: "Batch read users",
    0x0601: "QR key",
    0x0602: "QR online/offline",
}

OPEN_TYPES = {
    0x00: "invalid",
    0x10: "card",
    0x11: "ext. reader",
    0x20: "password",
    0x21: "user password",
    0x30: "fingerprint",
    0x40: "face",
    0x50: "QR code",
    0x51: "QR visitor",
    0x60: "remote/app",
    0x70: "back door",
    0x80: "exit button",
    0x90: "room call",
}


# --------------------------------------------------------------------------- frames

@dataclass
class Frame:
    head: int
    checksum: int
    length: int
    serial: int
    cmd: int
    type: int
    status: int
    data: bytes
    raw: bytes
    ok: bool  # checksum matches
    prefix: bytes = b""  # 8-byte ID block seen on the real device (not in the spec), else empty
    extra: dict = field(default_factory=dict)

    @property
    def cmd_name(self) -> str:
        return CMD_NAMES.get(self.cmd, f"cmd {self.cmd:04X}")

    @property
    def from_device(self) -> bool:
        return self.head == HEAD_DEVICE


# Real TCP-701 (firmware seen 2026-09-30) inserts an 8-byte ID block after the head byte:
#   Head(1) ID(8) Checksum(2) Length(2) Serial(4) Cmd(2) Type(1) Status(1) Data(N)
# The checksum still covers Length..Data. The parser accepts both layouts.
PREFIX_LEN = 8


def checksum(body: bytes) -> int:
    return sum(body) & 0xFFFF


def build(cmd: int, data: bytes = b"", serial: int = 1, typ: int = TYPE_REQ_NOREPLY,
          status: int = 0, head: int = HEAD_HOST, bad_checksum: bool = False,
          prefix: bytes = b"") -> bytes:
    body = struct.pack(">HIHBB", len(data), serial, cmd, typ, status) + bytes(data)
    ck = checksum(body)
    if bad_checksum:
        ck = (ck + 1) & 0xFFFF
    return bytes([head]) + bytes(prefix) + struct.pack(">H", ck) + body


def fix_checksum(raw: bytes, prefix_len: int = 0) -> bytes:
    """Recompute the checksum (and length) of a hand-typed frame."""
    hl = HEADER_LEN + prefix_len
    if len(raw) < hl:
        raise ValueError(f"frame too short ({len(raw)} bytes, need >= {hl})")
    body = struct.pack(">H", len(raw) - hl) + raw[5 + prefix_len:]
    return raw[:1 + prefix_len] + struct.pack(">H", checksum(body)) + body


def decode_frame(raw: bytes, prefix_len: int = 0) -> Frame:
    o = prefix_len
    head = raw[0]
    ck, ln, serial, cmd, typ, st = struct.unpack(">HHIHBB", raw[1 + o:HEADER_LEN + o])
    data = raw[HEADER_LEN + o:HEADER_LEN + o + ln]
    return Frame(head, ck, ln, serial, cmd, typ, st, bytes(data), bytes(raw),
                 checksum(raw[3 + o:HEADER_LEN + o + ln]) == ck, bytes(raw[1:1 + o]))


class FrameParser:
    """Stream reassembler for binary frames (either layout).

    feed() returns a list of Frame or bytes (junk that was skipped)."""

    MAX_LEN = 4096

    def __init__(self) -> None:
        self.buf = bytearray()
        self.layout: int | None = None  # prefix length of the last valid frame (0 or 8)

    def _try(self, o: int):
        """Try layout with prefix length o. Returns 'need', 'bad', or a Frame."""
        hl = HEADER_LEN + o
        if len(self.buf) < hl:
            return "need"
        ln = struct.unpack(">H", self.buf[3 + o:5 + o])[0]
        if ln > self.MAX_LEN:
            return "bad"
        if len(self.buf) < hl + ln:
            return "need"
        return decode_frame(bytes(self.buf[:hl + ln]), o)

    def feed(self, chunk: bytes) -> list:
        self.buf += chunk
        out: list = []
        while True:
            # resync to a head byte
            i = 0
            while i < len(self.buf) and self.buf[i] not in (HEAD_HOST, HEAD_DEVICE):
                i += 1
            if i:
                out.append(bytes(self.buf[:i]))
                del self.buf[:i]
            if not self.buf:
                return out
            std, ext = self._try(0), self._try(PREFIX_LEN)
            good = next((r for r in (std, ext) if isinstance(r, Frame) and r.ok), None)
            if good is not None:
                self.layout = len(good.prefix)
            elif isinstance(std, Frame) and ext == "need" and self.layout != PREFIX_LEN:
                good = std  # complete standard frame with bad checksum: report it now
            elif "need" in (std, ext):
                return out  # wait for more bytes before deciding
            if good is None:
                # neither layout checks out: emit the standard parse as a bad frame (visible in log)
                good = std if isinstance(std, Frame) else ext if isinstance(ext, Frame) else None
            if good is None:
                out.append(bytes(self.buf[:1]))
                del self.buf[:1]
                continue
            del self.buf[:len(good.raw)]
            out.append(good)

    def flush(self) -> bytes:
        rest, self.buf = bytes(self.buf), bytearray()
        return rest


HEX_CHARS = frozenset(b"0123456789ABCDEFabcdef")
TEXT_WS = frozenset(b" \r\n\t")


class WireDecoder:
    """Handles both transports: raw binary frames, or frames written as ASCII hex text
    (the real device sends e.g. 'AFFFFF...BB' as text). mode: auto | binary | ascii."""

    def __init__(self, mode: str = "auto") -> None:
        self.mode = mode
        self.detected: str | None = None
        self.text = ""
        self.parser = FrameParser()

    @property
    def wire(self) -> str:
        return self.mode if self.mode != "auto" else (self.detected or "unknown")

    def feed(self, chunk: bytes) -> list:
        if self.mode == "auto" and self.detected is None and chunk:
            self.detected = "ascii" if all(b in HEX_CHARS or b in TEXT_WS for b in chunk) else "binary"
        if self.wire != "ascii":
            return self.parser.feed(chunk)
        out: list = []
        junk = bytes(b for b in chunk if b not in HEX_CHARS and b not in TEXT_WS)
        if junk:
            out.append(junk)
        self.text += "".join(chr(b) for b in chunk if b in HEX_CHARS)
        n = len(self.text) // 2 * 2
        data, self.text = bytes.fromhex(self.text[:n]), self.text[n:]
        return out + self.parser.feed(data)

    def flush(self) -> bytes:
        rest = self.parser.flush()
        if self.text:
            rest += self.text.encode()
            self.text = ""
        return rest


# --------------------------------------------------------------------------- encodings

def to_bcd(n: int) -> int:
    return ((n // 10) << 4) | (n % 10)


def from_bcd(b: int) -> int:
    return (b >> 4) * 10 + (b & 0x0F)


def bcd_time(dt: datetime | None = None) -> bytes:
    """7-byte BCD time: ss mm hh ww DD MM YY. Weekday: 1=Mon..7=Sun (unconfirmed)."""
    dt = dt or datetime.now()
    return bytes(to_bcd(v) for v in (dt.second, dt.minute, dt.hour, dt.isoweekday(),
                                     dt.day, dt.month, dt.year % 100))


def decode_bcd_time7(b: bytes) -> str:
    s, m, h, w, d, mo, y = (from_bcd(x) for x in b[:7])
    return f"20{y:02d}-{mo:02d}-{d:02d} {h:02d}:{m:02d}:{s:02d} (wd {w})"


def decode_bcd_time6(b: bytes) -> str:
    y, mo, d, h, m, s = (from_bcd(x) for x in b[:6])
    return f"20{y:02d}-{mo:02d}-{d:02d} {h:02d}:{m:02d}:{s:02d}"


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def user_record(card: int = 0, pin: int = 0, uid: int = 1, group: int = 0,
                week: int = 0x7F, start_min: int = 0, end_min: int = 1439) -> bytes:
    """16-byte standard user. pin is the decimal PIN as an int (stored as 32-bit hex)."""
    return struct.pack(">IIHBBHH", card, pin, uid, group, week, start_min, end_min)


def temp_user(card: int = 0, pin: int = 0, uid: int = 1, expires: int = 0) -> bytes:
    """16-byte temporary user: group FF + Unix expiry timestamp."""
    return struct.pack(">IIHBIB", card, pin, uid, 0xFF, expires, 0)


def decode_user(b: bytes) -> dict:
    card, pin, uid, group = struct.unpack(">IIHB", b[:11])
    if group == 0xFF:
        exp = struct.unpack(">I", b[11:15])[0]
        return dict(card=f"{card:08X}", pin=pin, uid=uid, group="FF (temp)",
                    expires=datetime.fromtimestamp(exp).isoformat(sep=" "))
    week, start, end = struct.unpack(">BHH", b[11:16])
    return dict(card=f"{card:08X}", pin=pin, uid=uid, group=group, week=f"{week:02X}",
                window=f"{hhmm(start)}-{hhmm(end)}")


def decode_log(b: bytes) -> dict:
    return dict(
        type=f"{b[0]:02X} {OPEN_TYPES.get(b[0], '?')}",
        state={0xEC: "new", 0xFF: "invalid"}.get(b[1], f"{b[1]:02X}"),
        aux=b[2:6].hex().upper(),
        card=b[6:10].hex().upper(),
        time=decode_bcd_time6(b[10:16]),
    )


def decode_0215(d: bytes) -> dict:
    if len(d) == 2:
        return dict(kind=f"{d[0]:02X} {OPEN_TYPES.get(d[0], '?')}", status=f"{d[1]:02X}")
    if len(d) == 5:
        kind = OPEN_TYPES.get(d[0], "?")
        val = int.from_bytes(d[1:5], "big")
        out = dict(kind=f"{d[0]:02X} {kind}", value=d[1:5].hex().upper())
        if d[0] in (0x20, 0x21):
            out["pin"] = val
        return out
    if len(d) == 16:
        start = int.from_bytes(d[8:12], "big")
        end = int.from_bytes(d[12:16], "big")
        return dict(kind=f"{d[0]:02X} {OPEN_TYPES.get(d[0], '?')}", mode=f"{d[1]:02X}",
                    sub=f"{d[2]:02X}", dtype=f"{d[3]:02X}", value=d[4:8].hex().upper(),
                    start=f"{start:08X} ({ts_text(start)})", end=f"{end:08X} ({ts_text(end)})")
    # Unknown layout (e.g. raw QR text forwarded as-is) - show both hex and printable text.
    out = dict(len=len(d), raw=d.hex().upper())
    text = d.decode("ascii", "replace")
    if sum(32 <= b < 127 for b in d) >= 0.8 * len(d):
        out["text"] = text
    return out


def ts_text(ts: int) -> str:
    """Unix timestamp -> local time text, or '?' when it is not a plausible date."""
    if 946684800 <= ts <= 4102444800:  # 2000..2100
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    return "?"


# --------------------------------------------------------------------------- QR code
# Payload (76 bytes, big-endian) - SKILL.md §7. CRC32 = STM32 hardware style (verified).
QR_FIELDS = [("header", 2), ("dtype", 1), ("length", 1), ("card_id", 4), ("device_sn", 4),
             ("card_type", 1), ("ladder_uid", 2), ("perm_groups", 12), ("doors", 32),
             ("access_time", 1), ("reserve", 1), ("validity", 4), ("limit", 1),
             ("start", 4), ("duration", 2), ("crc", 4)]
QR_LEN = 76
QR_CRC_INIT = 0x16E008EC


def qr_crc32(data72: bytes) -> int:
    c = QR_CRC_INIT
    for i in range(0, len(data72), 4):
        c ^= int.from_bytes(data72[i:i + 4], "little")
        for _ in range(32):
            c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if c & 0x80000000 else (c << 1) & 0xFFFFFFFF
    return c


def rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray()
    for b in data:
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out.append(b ^ s[(s[i] + s[j]) & 0xFF])
    return bytes(out)


def door_bitmap(doors: list[int]) -> bytes:
    """32-byte permission bitmap: last byte bit0 = door address 1, bit1 = address 2, ..."""
    bm = bytearray(32)
    for n in doors:
        if 1 <= n <= 254:
            bm[31 - (n - 1) // 8] |= 1 << ((n - 1) % 8)
    return bytes(bm)


def doors_from_bitmap(bm: bytes) -> list[int]:
    return [n for n in range(1, 255) if bm[31 - (n - 1) // 8] >> ((n - 1) % 8) & 1]


def qr_key_bytes(key_hex: str, key_format: str = "raw16") -> bytes:
    """key_hex = 32 hex chars. raw16 -> the 16 bytes; ascii32 -> the 32 characters as ASCII."""
    k = key_hex.strip().upper()
    if len(k) != 32 or any(c not in "0123456789ABCDEF" for c in k):
        raise ValueError("QR key must be exactly 32 hex characters (16 bytes)")
    return bytes.fromhex(k) if key_format == "raw16" else k.encode("ascii")


def qr_key_0601_data(key_hex: str) -> bytes:
    """Data for command 0601: the 32 hex characters sent as ASCII (per spec example)."""
    qr_key_bytes(key_hex)  # validate
    return key_hex.strip().upper().encode("ascii")


def qr_plain(card_id: int, device_sn: int, doors: list[int], start: int, duration_min: int,
             validity: int, limit: int = 0, card_type: int = 0x01, ladder_uid: int = 0xFFF1,
             perm_groups: bytes = b"\xff" * 12, bad_crc: bool = False) -> bytes:
    body = (b"\x26\x18\x21\x48"
            + struct.pack(">IIBH", card_id, device_sn, card_type, ladder_uid)
            + perm_groups[:12].ljust(12, b"\xff")
            + door_bitmap(doors)
            + b"\xff\xff"
            + struct.pack(">IBIH", validity, limit, start, duration_min))
    crc = qr_crc32(body)
    if bad_crc:
        crc ^= 0x00000001
    return body + struct.pack(">I", crc)


def qr_parse_plain(pt: bytes) -> dict:
    """Split a 76-byte plaintext into fields + validity checks of its own structure."""
    out, i = {}, 0
    for name, size in QR_FIELDS:
        out[name] = pt[i:i + size]
        i += size
    info = {n: v.hex().upper() for n, v in out.items()}
    info["header_ok"] = out["header"] == b"\x26\x18" and out["dtype"] == b"\x21"
    info["crc_ok"] = qr_crc32(pt[:72]) == int.from_bytes(out["crc"], "big")
    start = int.from_bytes(out["start"], "big")
    dur = int.from_bytes(out["duration"], "big")
    validity = int.from_bytes(out["validity"], "big")
    info.update(
        card_id_int=int.from_bytes(out["card_id"], "big"),
        door_list=doors_from_bitmap(out["doors"]),
        start_text=ts_text(start), end_ts=start + dur * 60, end_text=ts_text(start + dur * 60),
        duration_min=dur, validity_text=ts_text(validity), limit_int=out["limit"][0],
    )
    return info


def qr_encode(plain: bytes, key: bytes, content_format: str = "hex_text") -> tuple[bytes, str | bytes]:
    """Encrypt; return (ciphertext, QR content). hex_text = uppercase hex string, binary = raw bytes."""
    ct = rc4(key, plain)
    return ct, (ct.hex().upper() if content_format == "hex_text" else ct)


def qr_decode_content(content: str | bytes, key: bytes) -> dict:
    """Decrypt QR content (hex text or raw bytes) and parse it."""
    if isinstance(content, str):
        s = re.sub(r"\s", "", content)
        ct = bytes.fromhex(s) if re.fullmatch(r"[0-9A-Fa-f]+", s or "x") and len(s) % 2 == 0 else s.encode("latin-1")
    else:
        ct = content
    if len(ct) != QR_LEN:
        return dict(error=f"expected {QR_LEN} bytes after decoding, got {len(ct)}")
    info = qr_parse_plain(rc4(key, ct))
    info["plain"] = rc4(key, ct).hex().upper()
    return info


def qr_check(info: dict, device_sn: int | None, door: int = 1, now: float | None = None) -> list[str]:
    """Server-side validation of a decrypted payload. Returns a list of problems (empty = valid)."""
    now = time.time() if now is None else now
    problems = []
    if "error" in info:
        return [info["error"]]
    if not info["header_ok"]:
        problems.append("bad header/type (wrong key?)")
    if not info["crc_ok"]:
        problems.append("CRC mismatch")
    if device_sn is not None and int(info["device_sn"], 16) != device_sn:
        problems.append(f"device SN {info['device_sn']} != {device_sn:08X}")
    if door not in info["door_list"]:
        problems.append(f"no permission for door {door}")
    start = int(info["start"], 16)
    if now < start:
        problems.append("not valid yet (start in future)")
    if now > info["end_ts"]:
        problems.append("QR expired")
    if now > int(info["validity"], 16):
        problems.append("account validity expired")
    return problems


STATUS_TEXT = {
    0x0501: {0: "ok", 1: "duplicate card", 2: "duplicate password", 3: "duplicate ID"},
}


def describe(f: Frame) -> str:
    """Human-readable one-line decode of a frame's payload."""
    d, c = f.data, f.cmd
    try:
        if f.type == TYPE_RESP and f.from_device and c in STATUS_TEXT and not d:
            return STATUS_TEXT[c].get(f.status, f"status {f.status}")
        if c == 0x0101 and len(d) >= 7:
            extra = f" + {d[7:].hex().upper()}" if len(d) > 7 else ""
            return f"device clock {decode_bcd_time7(d[:7])}{extra}"
        if c == 0x0001 and len(d) == 4:
            return f"device SN {d.hex().upper()}"
        if c == 0x0002 and len(d) == 2:
            return f"version {d.hex().upper()}"
        if c == 0x0003 and d:
            return {0x00: "start update", 0x01: "ready to receive"}.get(d[0], d.hex())
        if c == 0x0004 and len(d) == 1:
            return {0x38: "chunk OK", 0x02: "verify OK, updating", 0xFF: "verify FAILED"}.get(d[0], d.hex())
        if c == 0x0102 and d:
            return f"{d[0]} beep(s)"
        if c in (0x0103, 0x0104, 0x0105) and len(d) == 7:
            return decode_bcd_time7(d)
        if c == 0x0106 and d:
            return {0: "offline", 1: "online", 2: "mixed"}.get(d[0], d.hex())
        if c == 0x0107 and d:
            return {1: "card only", 2: "password only", 3: "card or password"}.get(d[0], d.hex())
        if c == 0x0108 and len(d) == 3:
            return f"doorbell type {d[0]:02X}, room {int.from_bytes(d[1:3], 'big')}"
        if c == 0x0108 and len(d) == 1:
            return "open door" if d[0] == 1 else "don't open"
        if c == 0x0109 and d:
            return "door OPEN" if d[0] == 1 else "door CLOSED"
        if c == 0x0201 and d:
            return f"unlock {d[0]} s" if d[0] else "unlock (default delay)"
        if c == 0x0202 and len(d) in (4, 8):  # spec: 2+2 bytes; real device: 4+4 bytes
            h = len(d) // 2
            return f"users {int.from_bytes(d[:h], 'big')}, records {int.from_bytes(d[h:], 'big')}"
        if c == 0x0203 and d:
            return "relay toggle mode" if d[0] == 0xFF else f"relay {d[0]} s"
        if c == 0x0204 and d:
            return {1: "time limit ON", 2: "time limit OFF"}.get(d[0], d.hex())
        if c == 0x0205 and len(d) == 2:
            return f"heartbeat every {int.from_bytes(d, 'big')} s"
        if c in (0x0210, 0x0211, 0x0213, 0x0214) and d and len(d) % 16 == 0:
            recs = [decode_log(d[i:i + 16]) for i in range(0, len(d), 16)]
            return " | ".join(f"{r['type']} {r['state']} card {r['card']} @ {r['time']}" for r in recs)
        if c == 0x0213 and len(d) == 2:
            return f"record #{int.from_bytes(d, 'big')}"
        if c == 0x0215 and d:
            return ", ".join(f"{k}={v}" for k, v in decode_0215(d).items())
        if c == 0x0501 and len(d) == 16:
            return ", ".join(f"{k}={v}" for k, v in decode_user(d).items())
        if c == 0x0502 and len(d) == 5:
            kind = {1: "card", 2: "password", 3: "user ID"}.get(d[0], "?")
            return f"delete by {kind} {d[1:].hex().upper()}"
        if c in (0x0504, 0x0505) and d:
            counted = c == 0x0504 and len(d) % 16 == 1  # batch add request: count byte first
            body = d[1:] if counted else d
            users = [decode_user(body[i:i + 16]) for i in range(0, len(body), 16)]
            prefix = f"{d[0]} users: " if counted else ""
            return prefix + " | ".join(f"{u['card']}/{u['pin']}/#{u['uid']}" for u in users)
        if c == 0x0601 and len(d) == 32:
            return f"key '{d.decode('ascii', 'replace')}'"
        if c == 0x0602 and d:
            return {1: "QR offline", 2: "QR online"}.get(d[0], d.hex())
    except Exception as e:  # never let decoding break the traffic log
        return f"(decode error: {e})"
    if f.type == TYPE_RESP and f.from_device:
        return "OK" if f.status == 0 else f"status {f.status}"
    return d.hex().upper() if d else ""


def frame_fields(f: Frame) -> list[tuple[str, str]]:
    """(field name, hex) pairs for colour-coded display."""
    r, o = f.raw, len(f.prefix)
    fields = [("head", r[0:1].hex().upper())]
    if o:
        fields.append(("id", f.prefix.hex().upper()))
    return fields + [
        ("checksum", r[1 + o:3 + o].hex().upper()),
        ("length", r[3 + o:5 + o].hex().upper()),
        ("serial", r[5 + o:9 + o].hex().upper()),
        ("cmd", r[9 + o:11 + o].hex().upper()),
        ("type", r[11 + o:12 + o].hex().upper()),
        ("status", r[12 + o:13 + o].hex().upper()),
        ("data", r[13 + o:].hex().upper()),
    ]
