"""Golden vectors from .claude/skills/tcp701-protocol/reference/frames.md."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import protocol as p  # noqa: E402

GOLDEN = [
    "FA000A0001000000010201000005",
    "FA000300000000000100010100",
    "AF00090004000000010001020000000001",
    "FA000400000000000100020100",
    "AF0008000200000001000202000001",
    "FA00060001000000010003010000",
    "AF00080001000000010003020001",
    "AF00400001000000010004020038",
    "FA000300000000000101010000",
    "AF000300000000000101010000",
    "FA00090001000000010102010003",
    "AF000600000000000101020200",
    "FA00AB0007000000010103010010321006180925",
    "FA00860007000000010104010000001706300625",
    "FA00900007000000010105010000081806300625",
    "FA000A0001000000010106010000",
    "FA000E0001000000010107010003",
    "AF0177000300000002010803009004D2",
    "FA000F0001000000020108020001",
    "AF00100001000000010109030001",
    "FA000B00000000000101090000",
    "FA000B0001000000010201010005",
    "AF000D0004000000010202020000000002",
    "FA00090001000000010203010001",
    "FA000B0001000000010204010002",
    "FA0083000200000001020501000078",
    "AF02380010000000010210020080EC0000000000000000250918140746",
    "AF04AB0020000000010211020070EC000000000000000025081122475580EC0000000000000000250811224809",
    "FA0019000200000001021301000000",
    "AF027D000500000001021503001036F2E63F",
    "FA052A0010000000010501010000BC614E00A98AC70011007F01FE041A",
    "FA025C000500000001050201000136F2E63F",
    "FA0796002000000001060101004442304143384232384641423431313838423941424434443530453041314436",
    "FA000C0001000000010602010001",
    "FA0468001000000001050101007D414929000D90380011FF690703C800",
]


@pytest.mark.parametrize("hexstr", GOLDEN)
def test_golden_roundtrip(hexstr):
    raw = bytes.fromhex(hexstr)
    frames = p.FrameParser().feed(raw)
    assert len(frames) == 1 and isinstance(frames[0], p.Frame)
    f = frames[0]
    assert f.ok, "checksum"
    rebuilt = p.build(f.cmd, f.data, f.serial, f.type, f.status, f.head)
    assert rebuilt == raw
    assert p.fix_checksum(raw) == raw
    p.describe(f)  # must not raise


def test_spec_typo_heartbeat_is_short():
    frames = p.FrameParser().feed(bytes.fromhex("FA0003000000000101010000"))
    assert not any(isinstance(x, p.Frame) for x in frames)


def test_stream_reassembly_and_junk():
    a = bytes.fromhex("AF0008000200000001000202000001")
    b = bytes.fromhex("AF000D0004000000010202020000000002")
    parser = p.FrameParser()
    out = parser.feed(b"\x00\x11" + a[:5]) + parser.feed(a[5:] + b[:3]) + parser.feed(b[3:])
    assert out[0] == b"\x00\x11"
    assert [x.cmd for x in out[1:]] == [0x0002, 0x0202]


def test_bad_checksum_flagged():
    raw = p.build(0x0002, bad_checksum=True)
    (f,) = p.FrameParser().feed(raw)
    assert not f.ok


def test_bcd_time():
    assert p.bcd_time(datetime(2025, 9, 18, 10, 32, 10)).hex().upper() == "10321004180925"  # Thu = 4
    assert p.decode_bcd_time7(bytes.fromhex("10321006180925")).startswith("2025-09-18 10:32:10")


def test_user_records():
    assert p.user_record(0x00BC614E, 11111111, 0x11, 0, 0x7F, 510, 1050).hex().upper() == "00BC614E00A98AC70011007F01FE041A"
    assert p.temp_user(0x7D414929, 888888, 0x11, 0x690703C8).hex().upper() == "7D414929000D90380011FF690703C800"
    u = p.decode_user(bytes.fromhex("00BC614E00A98AC70011007F01FE041A"))
    assert u["pin"] == 11111111 and u["window"] == "08:30-17:30"


def test_log_and_0215_decoders():
    r = p.decode_log(bytes.fromhex("80EC0000000000000000250918140746"))
    assert r["type"].endswith("exit button") and r["state"] == "new" and r["time"] == "2025-09-18 14:07:46"
    assert p.decode_0215(bytes.fromhex("1036F2E63F"))["value"] == "36F2E63F"
    assert p.decode_0215(bytes.fromhex("210001E240"))["pin"] == 123456


# ---------------------------------------------------------------- QR
SPEC_QR_PLAIN = bytes.fromhex(
    "2618214800000457111111115500010000000000000000000000840000000000000000000000000000000000"
    "000000000000000000000000000001FFFF5FCC2D10005DED9C9005A0802916C8")
KEY = "DB0AC8B28FAB41188B9ABD4D50E0A1D6"


def test_qr_crc_matches_spec_example():
    assert p.qr_crc32(SPEC_QR_PLAIN[:72]) == 0x802916C8
    info = p.qr_parse_plain(SPEC_QR_PLAIN)
    assert info["crc_ok"] and info["header_ok"] and info["door_list"] == [1] and info["duration_min"] == 1440


def test_qr_plain_layout_and_crc():
    pt = p.qr_plain(0xE54CA721, 0x457, [1, 9], 1_700_000_000, 5, 1_800_000_000, limit=2)
    assert len(pt) == p.QR_LEN and pt[:4] == b"\x26\x18\x21\x48"
    info = p.qr_parse_plain(pt)
    assert info["crc_ok"] and info["card_id"] == "E54CA721" and info["door_list"] == [1, 9]
    assert info["limit_int"] == 2 and info["end_ts"] == 1_700_000_000 + 300
    assert not p.qr_parse_plain(p.qr_plain(1, 1, [1], 0, 5, 0, bad_crc=True))["crc_ok"]


def test_door_bitmap():
    assert p.door_bitmap([1]) == bytes(31) + b"\x01"
    assert p.door_bitmap([9]) == bytes(30) + b"\x01\x00"
    assert p.doors_from_bitmap(p.door_bitmap([1, 2, 200])) == [1, 2, 200]


def test_qr_key_formats_and_0601():
    assert p.qr_key_bytes(KEY, "raw16") == bytes.fromhex(KEY)
    assert p.qr_key_bytes(KEY, "ascii32") == KEY.encode()
    assert p.qr_key_0601_data(KEY).hex().upper() == "4442304143384232384641423431313838423941424434443530453041314436"
    with pytest.raises(ValueError):
        p.qr_key_bytes("1234")


@pytest.mark.parametrize("fmt", ["raw16", "ascii32"])
@pytest.mark.parametrize("content_fmt", ["hex_text", "binary"])
def test_qr_encrypt_decode_roundtrip(fmt, content_fmt):
    now = 1_760_000_000
    pt = p.qr_plain(0x1234, 0x457, [1], now - 60, 5, now + 86400)
    key = p.qr_key_bytes(KEY, fmt)
    ct, content = p.qr_encode(pt, key, content_fmt)
    assert p.rc4(key, ct) == pt
    info = p.qr_decode_content(content, key)
    assert info["plain"] == pt.hex().upper()
    assert p.qr_check(info, 0x457, 1, now) == []


def test_qr_check_rejections():
    now = 1_760_000_000
    key = p.qr_key_bytes(KEY)
    dec = lambda pt: p.qr_decode_content(p.qr_encode(pt, key)[1], key)
    assert "QR expired" in p.qr_check(dec(p.qr_plain(1, 5, [1], now - 3600, 5, now + 9)), 5, 1, now)
    assert any("future" in x for x in p.qr_check(dec(p.qr_plain(1, 5, [1], now + 3600, 5, now + 9999)), 5, 1, now))
    assert any("device SN" in x for x in p.qr_check(dec(p.qr_plain(1, 6, [1], now, 5, now + 9)), 5, 1, now))
    assert any("door" in x for x in p.qr_check(dec(p.qr_plain(1, 5, [2], now, 5, now + 9)), 5, 1, now))
    assert "account validity expired" in p.qr_check(dec(p.qr_plain(1, 5, [1], now, 5, now - 1)), 5, 1, now)
    assert "CRC mismatch" in p.qr_check(dec(p.qr_plain(1, 5, [1], now, 5, now + 9, bad_crc=True)), 5, 1, now)
    wrong = p.qr_decode_content(p.qr_encode(p.qr_plain(1, 5, [1], now, 5, now + 9), key)[1],
                                p.qr_key_bytes("00" * 16))
    assert p.qr_check(wrong, 5, 1, now)  # garbage after wrong-key decrypt


def test_0215_raw_text_fallback():
    d = p.decode_0215(b"HELLO-QR-TEXT")
    assert d["text"] == "HELLO-QR-TEXT"
