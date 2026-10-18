---
name: tcp701-protocol
description: Complete reference for the TCP-701 networked QR/IC-card access-control device (Gymwale check-in hardware) — binary FA/AF frame format, checksum, every command (0x0001–0x0602), user/log/time encodings, device-initiated events (heartbeat, door sensor, doorbell, real-time swipe), OTA flow, encrypted QR payload (CRC32 + RC4), network defaults and wiring. Use whenever building, decoding, sending or debugging TCP-701 frames, writing a test harness/server for the device, unlocking the door, managing cards/users/logs, or generating QR codes for it.
---

# TCP-701 Access Control — Protocol Skill

Source documents (project root, vendor translations — tables are garbled, some examples have typos):
- `TCP-701Networked QR code encrypted version access control protocolAPI(V1).doc` — command protocol (doc rev V3.0, 2025-10-05)
- `TCP-701Network Configuration Instructions.docx` — network module (NA11x-style serial server) config
- `TCP-701Network QR code access control machine.docx` — hardware manual

Supporting files in this skill:
- [reference/frames.md](reference/frames.md) — every spec example frame decoded + checksum-verified (golden test vectors)
- [reference/test-checklist.md](reference/test-checklist.md) — feature-by-feature test plan for the physical device

---

## 1. Device quick facts

| Item | Value |
|---|---|
| Power | 9–24 V DC, ~40 mA |
| Readers | 13.56 MHz IC/NFC (ISO14443A, 5–8 cm), QR/barcode/DataMatrix/PDF417 (≤30 cm), touch keypad |
| Capacity | 20,000 users, 60,000 offline log records |
| Network | RJ45, IPv4, static (default) or DHCP, custom DNS |
| Default IP | `192.168.3.7`, mask `255.255.255.0`, gateway `192.168.3.1` |
| Default mode | **TCP Server**, local port **8887**, up to **6** simultaneous clients |
| Client-mode target | `192.168.3.3:8888` (when set to TCP/UDP Client, device connects to this) |
| Other modes | UDP Server/Client, HTTP Client (GET/POST), MQTT Client (3.1.1, Aliyun/Baidu/OneNET/Huawei), Modbus gateway |
| Web config | `http://192.168.3.7` (port 80, configurable), password **123456** (6 alnum). Use Chrome/Edge, not IE. **Entering web config halts communication mode — reboot device afterwards.** |
| Other config | Vendor config tool (Ethernet only, one host per LAN, disable extra NICs), AT commands |
| Module extras | Heartbeat packet (serial/network, ≤40 B ASCII/20 B HEX; disabled by default), registration packet (OLMAC/OLCSTM/EMBMAC/EMBCSTM), timeout-restart (default 300 s, 0=off), reconnect interval/count, clear-cache-on-connect |

> The *network module* heartbeat/registration packets (configured via web/tool) are **different** from the protocol heartbeat command 0x0101. Keep module heartbeat/registration **off** when talking the FA/AF protocol, otherwise extra bytes are injected into the stream.

### Wiring (9-wire harness)
| # | Colour | Signal | Use |
|---|---|---|---|
| 1 | Red | VCC | +9–24 V DC |
| 2 | Black | GND | Power ground |
| 3 | Green | OPEN | Exit button — short to GND to open |
| 4 | White | MC | Door magnet (contact) feedback → triggers 0x0109 |
| 5 | Blue | D0 | External Wiegand-26 reader D0 |
| 6 | Yellow | D1 | External Wiegand-26 reader D1 |
| 7 | Gray | NC | Relay normally-closed |
| 8 | Brown | COM | Relay common |
| 9 | Purple | NO | Relay normally-open |

Fail-secure lock (unlocks on power) → COM + NO. Fail-safe maglock (locks on power) → COM + NC.

---

## 2. Frame format

> **CONFIRMED ON REAL DEVICE (2026-09-30, serial BB900021, EBT3001 network module fw 9013-2-17):**
> 1. Frames travel as **ASCII hex text** (e.g. the 58 characters `AFFFFFFFFFFFFFFFFF029C0008BB9000210101000009180203160926BB`), not raw bytes. Binary requests get no reply.
> 2. The device inserts an **8-byte ID block (`FF×8`) right after the head byte**. This is not in the spec:
>    `Head(1) ID(8) Checksum(2) Length(2) Serial(4) Cmd(2) Type(1) Status(1) Data(N)`. The checksum still covers Length..Data.
> 3. Unprompted **0101 heartbeat every 60 s once acked (every ~1 s while unacked)**: Type 00, data = 7-byte BCD clock (sec min hour weekday day month year; Fri = 05) + `BB`. The clock was wrong until synced and **falls behind** (~1–2 s per reconnect plus a few s/hour; −8 s after 2.5 h), so re-sync 0103 on connect.
> 3b. **Undocumented vendor command 0000 rewrites the serial** (tested 2026-10-18): `FA FF×8 ck 0008 <current serial> 0000 01 00 AFFFAC88 <new serial>`; fixed `FFFFFFFF` → `BB900021` after the 2026-10-03 incident (a hung 0601 wiped the serial).
> 4. The frame's Serial field carries the device serial (`BB900021`), not `00000001`.
> 5. Host frames **with** the FF×8 ID block and the device serial, sent as ASCII, are answered (0002 → `0004`). 0001 → `BB900021` (answered from 2026-10-02; the first tries got no reply before the format was learned).
> 6. **0202 reply is 8 bytes**: 4-byte users + 4-byte records (spec says 2+2).
> 7. On connect, the device pushes **all stored un-uploaded records as 0214** (Type 02), one per second; the ack `FA 0214 Type02` with no data advances it.
>
> Whether the host must include the ID block in its frames is still open (the tool copies the device's by default).
> The spec layout below remains valid **after** removing the ID block.

Frames as described by the spec (the spec's widths "2 4 4 8 4 2 2 N" are *hex-character* counts). All multi-byte fields are **big-endian**.

```
Offset  Size  Field      Notes
0       1     Head       0xFA = frame sent by host/server; 0xAF = frame sent by device
1       2     Checksum   16-bit sum of every byte from Length (offset 3) to end of Data, & 0xFFFF
3       2     Length     number of Data bytes only (N)
5       4     Serial     device serial number (examples use 00000001; read it with 0x0001)
9       2     Cmd        command word
11      1     Type       0x00 request (reply required), 0x01 request (reply "not required"),
                         0x02 response, 0x03 unsolicited message from device MCU
12      1     Status     0x00 in requests; in responses 0x00 = success, else per-command code
13      N     Data       optional
```
Minimum frame = 13 bytes. Total length = 13 + Length.

**Head direction rule**: whoever *originates* a frame on the wire uses its own head: host→device is always `FA`, device→host is always `AF` — including the host's reply to a device event (e.g. host reply to 0x0108 is `FA … Type 02`).

**Type 01 in practice**: every spec example request uses Type 01 and still shows a response. Expect a reply either way; confirm on hardware.

### Checksum — worked example (unlock 5 s)
```
FA | 000A | 0001 | 00000001 | 0201 | 00 | 00 | 05
checksum = 00+01 + 00+00+00+01 + 02+01 + 00 + 00 + 05 = 0x0A  ✅
```
**Trust the checksum formula over printed examples** — the spec has a few typos (see §9). All examples were machine-verified in [reference/frames.md](reference/frames.md).

### Minimal codec (Python)
```python
import struct
def build(cmd, data=b"", serial=1, typ=0x01, status=0, head=0xFA):
    body = struct.pack(">HIHBB", len(data), serial, cmd, typ, status) + data
    return struct.pack(">BH", head, sum(body) & 0xFFFF) + body

def parse(buf):
    """Return (frame_dict, remaining_bytes) or (None, buf) if incomplete. Resync on 0xFA/0xAF."""
    while buf and buf[0] not in (0xFA, 0xAF): buf = buf[1:]
    if len(buf) < 13: return None, buf
    head, ck, ln, serial, cmd, typ, st = struct.unpack(">BHHIHBB", buf[:13])
    if len(buf) < 13 + ln: return None, buf
    data = buf[13:13+ln]
    ok = (sum(buf[3:13+ln]) & 0xFFFF) == ck
    return dict(head=head, ok=ok, len=ln, serial=serial, cmd=cmd, type=typ, status=st, data=data), buf[13+ln:]
```
TCP is a stream: always reassemble with Length, and resync by scanning for FA/AF if a checksum fails.

---

## 3. Data encodings

### 3.1 Date/time (7 bytes, BCD) — used by 0x0103/0x0104/0x0105
`ss mm hh ww DD MM YY` — e.g. `10 32 10 06 18 09 25` = 2025-09-18 10:32:10, week-day 6.
Week-day convention is not stated (examples don't match the real weekday) — probably 1=Mon…7=Sun; verify on device.

### 3.2 Log timestamp (6 bytes, BCD) — `YY MM DD hh mm ss`, e.g. `25 09 18 14 07 46`.

### 3.3 Standard user record (16 bytes) — 0x0501, 0x0504, 0x0505
| Bytes | Field | Encoding |
|---|---|---|
| 1–4 | Card number | 32-bit hex, e.g. `00BC614E` = 12345678 |
| 5–8 | Password | decimal PIN stored as 32-bit hex, e.g. `00A98AC7` = 11111111, `0153158E` = 22222222 |
| 9–10 | User ID / serial | 16-bit, unique per user, e.g. `0011` |
| 11 | Group | `00` = no time restriction; `01`–`08` = time-limited group |
| 12 | Weekday mask | bit0..bit6 = days, `7F` = every day (`0` bit = not valid that day) |
| 13–14 | Daily start | minutes since midnight: `01FE` = 510 = 08:30 |
| 15–16 | Daily end | minutes since midnight: `041A` = 1050 = 17:30 |

Unused card/password → use `00000000` (verify; examples always set both). Time window only enforced when time-limit is enabled (0x0204 = 01) and group ≠ 0.

### 3.4 Temporary (visitor) user record (16 bytes) — sent with 0x0501
| Bytes | Field |
|---|---|
| 1–4 | Card number |
| 5–8 | Password (hex of decimal PIN; `000D9038` = 888888) |
| 9–10 | User ID |
| 11 | `FF` = temporary user marker |
| 12–15 | Expiry, Unix timestamp (s), big-endian (e.g. `690703C8`) |
| 16 | `00` reserved |

### 3.5 Door-open log record (16 bytes) — 0x0210/0x0211/0x0213/0x0214
| Byte(s) | Field |
|---|---|
| 1 | Open type (table below) |
| 2 | Record state: `EC` = new (not yet uploaded), `FF` = invalid/empty |
| 3–6 | Aux data (password used, fingerprint/face index…) |
| 7–10 | Card number |
| 11–16 | BCD `YY MM DD hh mm ss` |

Open types: `00` invalid · `10` card · `11` external (Wiegand) reader · `20` password (admin/general) · `21` user password · `30` fingerprint · `40` face · `50` QR code · `51` QR temporary visitor · `60` app/remote open · `70` back door · `80` exit button · `90` room call (doorbell).
Example: `80 EC 00000000 00000000 250918140746` = exit button, new, 2025-09-18 14:07:46.

---

## 4. Command reference

Dir: H→D = host sends `FA`, device replies `AF`. D→H = device originates `AF`, host replies `FA`.

### 4.0 Device info & OTA
| Cmd | Name | Dir | Request data | Response data / status |
|---|---|---|---|---|
| 0001 | Get hardware ID / serial | H→D | — | 4 B device serial number |
| 0002 | Get firmware version | H→D | — | 2 B version (e.g. `0001`) |
| 0003 | OTA start / end | H→D | 1 B: `00` = start update (device erases program area, LED turns green ~1 s) | `01` = ready to receive |
| 0004 | OTA data packet | H→D | 256 B firmware chunk (final packet: 2-byte checksum) | `38` = chunk OK · `02` = final check OK, updating · `FF` = check failed, OTA aborted |

### 4.1 Settings & events
| Cmd | Name | Dir | Request data | Response |
|---|---|---|---|---|
| 0101 | Heartbeat | see §5 | — | — (reply clears device's miss counter) |
| 0102 | Beep | H→D | 1 B: `01`/`02`/`03` beeps | status 0 |
| 0103 | Sync clock | H→D | 7 B BCD time (§3.1) | status 0 |
| 0104 | Set device valid-from | H→D | 7 B BCD time | status 0 |
| 0105 | Set device valid-until | H→D | 7 B BCD time | status 0 |
| 0106 | Online/offline mode | H→D | 1 B: `00` offline (local check only) · `01` online (server decides every access) · `02` mixed (local first, then server) — **default 02** | status 0 |
| 0107 | Open mode | H→D | 1 B: `01` card only · `02` password only · `03` card or password (**default**) | status 0 |
| 0108 | Doorbell / room call | D→H | 3 B: `90` + 2 B room no. (e.g. `04D2` = room 1234) | Host reply `FA…0108 Type02` data 1 B: `00` don't open · `01` open door |
| 0109 | Door sensor state | D→H | 1 B: `01` open · `00` closed | Host reply `FA…0109` no data |

0104/0105 appear to bound the whole device's validity window (spec: "valid start/end time") — test carefully, a past end time may lock everyone out.

### 4.2 Door & records
| Cmd | Name | Dir | Request data | Response |
|---|---|---|---|---|
| 0201 | Unlock (remote open) | H→D | 1 B seconds; `00` = use configured default delay | status 0 = opened |
| 0202 | Read counts | H→D | — | 4 B: 2 B total users + 2 B total records |
| 0203 | Set relay hold time | H→D | 1 B seconds; `FF` = relay trigger (toggle) mode | status 0 |
| 0204 | Time-limit feature | H→D | `01` enable · `02` disable | status 0 |
| 0205 | Heartbeat interval | H→D | 2 B seconds (max 65535), e.g. `0078` = 120 s | status 0 |
| 0210 | Read **new** (un-uploaded) records | H→D | — | N×16 B records, batches of up to 8; host must answer each batch before the next arrives |
| 0211 | Read **all** records | H→D | — | N×16 B, batches of up to 8, ack each batch. **Real device (2026-10-02): sends only the first batch; no ack format accepted (8 tried) → use 0213 one by one** |
| 0212 | **Format (erase) all records** ⚠ | H→D | — | status 0 |
| 0213 | Read single record | H→D | 2 B record index, 0000 = oldest | 16 B record; all-FF = past the last record. **Confirmed 2026-10-02: the reliable way to download all records** |
| 0214 | Real-time record push | D↔H | host request enables; device pushes each new 16 B record, expects ack (~1 s spacing) | 16 B record |
| 0215 | Real-time verification request | D→H (Type 03) | see below | host decides (see §5) |

**0x0215 payload variants** (sent in online/mixed mode when the device needs the server to decide):
- **2 B**: `80 00` — exit-button event (type 80, status 00).
- **5 B**: type + 4 B value — `10` + card number, or `21` + password (hex → convert to decimal PIN). Example `10 36F2E63F`.
- **16 B**: online QR: `50`, mode byte, sub byte, data-type byte, 4 B card/password, 4 B start time, 4 B end time.

### 4.3 Users / cards
| Cmd | Name | Dir | Request data | Response status |
|---|---|---|---|---|
| 0501 | Add user | H→D | 16 B user record (§3.3) or temp user (§3.4) | 0 ok · 1 dup card · 2 dup password · 3 dup user ID |
| 0502 | Delete | H→D | 1 B type + 4 B key: `01`+card (removes card, keeps PIN) · `02`+password (keeps card) · `03`+user ID (deletes whole user; ID in 4 B field, right-aligned — verify) | 0 ok · 1 fail |
| 0503 | **Format all users** ⚠ | H→D | — | 0 ok · 1 fail |
| 0504 | Batch add | H→D | 1 B count (≤16 = `10`) + count×16 B | 0 = all ok; otherwise Data = the rejected 16 B records |
| 0505 | Batch read (download) | H→D | — | up to 16×16 B per packet; ack each packet before next. **Real device 2026-10-03: do NOT ack — our ack makes it re-send the same packet immediately (endless loop, device reconnects). Deleted users remain as all-00 slots and are not reused; 0202 counts slots.** |

### 4.4 QR code
| Cmd | Name | Dir | Request data | Response |
|---|---|---|---|---|
| 0601 | Set QR RC4 key ⚠ | H→D | 32 B = ASCII of 32-hex-char key (the 16-byte key written as hex text), e.g. key `DB0AC8B2…A1D6` → data `44 42 30 41 …` | status 0 |
| 0602 | QR verify mode | H→D | `01` offline (device decrypts/validates locally) · `02` online (forwards via 0215) | status 0. **Confirmed 2026-10-02: offline needs (1) RC4 key = the 32 ASCII chars sent with 0601 ("ascii32"), QR = hex text; (2) the QR user ID present as a card number in the user list (0501), else refused (3 beeps, 0214 state FF). Each offline scan → 0214 type 50 + card number. Offline checks: user list, account validity (to the second), use limit, key+CRC (bad = silently ignored); the QR start+duration, device SN and door bitmap are IGNORED (tested 2026-10-03) → use a different key per device. The device reads its clock as UTC+8: with local India time on the clock, write QR timestamps as real epoch − 9000 s. Short-lived offline QR = account validity of now − 9000 s + N min (tested).** |

---

## 5. Device-initiated flows (the host must act as a server)

- **Heartbeat 0101** — interval set by 0205. Spec: host replies to clear the counter; if **3 consecutive heartbeats go unanswered, the device stops auto-uploading records** until the server replies again. Direction/head bytes in the spec are ambiguous (example labelled "card reader sends FA…"); the harness should reply to any 0101 it receives with `FA …0101 Type02 Status00` and also be ready to send 0101 itself. Confirm on hardware.
- **Door sensor 0109** / **Doorbell 0108** — device repeats **every 5 s until acknowledged**. For 0108 the reply data `01` remotely opens the door; `*` on keypad or remote open stops ringing.
- **Real-time verification 0215** (online or mixed mode) — device sends Type 03; host must answer promptly. Exact grant/deny encoding is **not specified**: try (a) reply `FA…0215 Type02 Status00` = allow / `Status01` = deny, and/or (b) send `0201` unlock. Determine on hardware and record the result here.
- **Record upload 0210/0211/0214/0505** — device sends batches (8 records or 16 users) and waits for host ack before the next batch. Ack = `FA` same cmd, Type 02, Status 00, no data (spec: "wait for a response… response takes 88 bytes" is unclear — confirm).

Recommended harness behaviour: always keep a reader thread that logs every raw frame (hex + decode), auto-acks 0101/0108/0109/0214, and routes responses to pending requests by Cmd.

---

## 6. OTA update procedure ⚠ (can brick the device)
1. `0002` — read current version.
2. `0003` data `00` — device erases program area; wait ~1 s for green LED and response data `01`.
3. For each 256-byte chunk of firmware: `0004` data = chunk → expect `38`.
4. Send `0004` with the 2-byte firmware checksum (sum of all firmware bytes & 0xFFFF — "byte and" check; verify) → `02` success & reboot, `FF` failure (device exits update).
Pad the last chunk as the vendor tool does (unknown — ask vendor). Never test OTA without vendor firmware + recovery path.

---

## 7. Encrypted QR code payload (offline QR mode)

Plaintext is 76 bytes (big-endian fields):

| Off | Size | Field | Value / rule |
|---|---|---|---|
| 0 | 2 | Header | `26 18` |
| 2 | 1 | Data type | `21` |
| 3 | 1 | Length | `48` (72 = bytes after this field) |
| 4 | 4 | User card ID | IC card UID, high byte first (e.g. 3847005985 → `E54CA721`) |
| 8 | 4 | Device SN | networked device serial (from 0x0001) |
| 12 | 1 | Card type | `01` = IC card (spec example uses `55`) |
| 13 | 2 | Ladder user ID | 1–65534, or `FFF1` if no elevator control |
| 15 | 12 | Elevator permission groups | 6 × 2 B; `FF…` if unused |
| 27 | 32 | Door permission bitmap | 256 bits; **last byte bit0 = door address 1**, bit1 = address 2 … (addresses 0 & 255 reserved). Door 1 only → 31×`00` + `01` |
| 59 | 1 | Access time | reserved `FF` |
| 60 | 1 | Reserve | `FF` |
| 61 | 4 | Account validity | Unix timestamp — master expiry (app/mini-program subscription) |
| 65 | 1 | Use limit | 0–9, `0` = unlimited |
| 66 | 4 | QR valid-from | Unix timestamp (s) |
| 70 | 2 | QR duration | minutes, max 2880 (`< 0x0B40`) |
| 72 | 4 | CRC32 | over bytes 0–71, see below; stored big-endian |

**CRC32 (verified against the spec example)** — STM32 hardware-CRC style:
```python
def qr_crc32(data72: bytes) -> int:
    c = 0x16E008EC                                   # init
    for i in range(0, 72, 4):
        c ^= int.from_bytes(data72[i:i+4], "little") # 32-bit words, little-endian
        for _ in range(32):
            c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if c & 0x80000000 else (c << 1) & 0xFFFFFFFF
    return c                                          # no final XOR; append .to_bytes(4,"big")
```
(Standard zlib/reflected CRC32 does **not** match.)

**Encryption**: RC4 over all 76 bytes with the manufacturer-provided key (same key loaded into the device via 0x0601). The QR content is the ciphertext as **uppercase hex text** (152 chars). The spec's example key is not the 0601 example key — the example's RC4 key is unknown.

Spec example plaintext (CRC verified):
`2618 21 48 00000457 11111111 55 0001 000000000000000000000084 00…01 FF FF 5FCC2D10 00 5DED9C90 05A0 802916C8`
→ start 2019-12-09 09:00 (UTC+8), 24 h (`05A0` = 1440 min), unlimited uses.

Display: ~2.5 cm / 150 px, error correction **Low**, black on white, ≥5 mm quiet zone; app should max screen brightness while showing.

---

## 8. Safety — confirm with the user before sending
| Command | Risk |
|---|---|
| 0003 / 0004 | OTA — can brick the device |
| 0212 | Erases all door-open logs |
| 0503 | Erases all users/cards |
| 0502 type 03 | Deletes a whole user |
| 0106 / 0602 | Online mode without a working server = nobody gets in |
| 0104 / 0105 | Wrong validity window may lock the device |
| 0601 | Changing the QR key invalidates all issued QR codes |
| 0107 | Card-only/password-only may lock out existing users |
Before destructive tests, back up users (0505) and logs (0211).

---

## 9. Spec errata (verified by recomputing checksums)
- Heartbeat 0101 "card reader sends" example `FA0003000000000101010000` is **missing 2 hex digits**; correct form `FA 0003 0000 00000001 0101 00 00`.
- 0602 response example echoes cmd `0601` — expect `0602`.
- 0108/0109 prose says "Starting byte: FA/AF" opposite to the hex shown; hex (device=AF, host=FA) is correct.
- User time example says 17:03 but `041A` = 1050 = **17:30**.
- "8-bit password" means 8-**digit** decimal PIN stored as 32-bit hex.
- 0004 example data is copy-pasted user records (illustrative only).
- 0103 example weekday (06) doesn't match the real weekday of 2025-09-18 (Thursday).
- QR example card type is `55`, text says `01`.

## 10. Open questions — resolve on hardware, then update this file
1. Who initiates 0101 heartbeat, and exact ack format?
2. How the host grants/denies a 0215 request (status in reply vs separate 0201).
3. Ack format for batched uploads (0210/0211/0505) and 0214 stream.
4. Does Type 01 suppress the reply?
5. Is the Serial field checked (does a wrong SN get rejected)? Default device SN?
6. "Reverse card number" option (V2.0 changelog) — byte order of card numbers from reader vs. stored.
7. Keypad features from V2.0: room number entry, `*` silences buzzer. ✔ **PIN entry confirmed (2026-10-03):** PIN stored in the user record as a big-endian number (654321 → `0009FBF1`). Checked locally (no 0215, even with QR online). Log type `21`, state `EC`/`FF`, bytes 3–6 = **typed PIN**, e.g. `21EC0009FBF100000000261003200027`.
8. Weekday numbering in BCD time; bit order of weekday mask.
9. 0502 type 03 data layout for user ID.
10. OTA final checksum algorithm & last-chunk padding.
