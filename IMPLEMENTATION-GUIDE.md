# TCP-701 — Implementation Guide (Gymwale check-in)

Everything a server implementation needs to know about the TCP-701, based on tests on the real device
(serial `BB900021`, firmware `0004`, network module EBT3001) on 2026-09-30 → 2026-10-03.
✔ = confirmed on the device · ❓ = not confirmed · ⚠ = pitfall.
Details and raw evidence: `DEVICE-NOTES.md`, `COMMANDS.txt`, `TESTING-PLAN.md` (findings log), `tools/tcp701-tester/logs/`.

---

## 1. Device and network

- QR scanner + IC card reader + keypad, drives one door relay (magnetic lock). Exit button input (OPEN–GND), door sensor input (MC), Wiegand input.
- Capacity (manual): **20,000 users**, **60,000 stored door records**.
- Two parts inside: a network module (Ethernet, its own web page) and the access controller. They talk over an internal serial link (115200 8N1; don't change it).
- **Work mode: TCP Client.** The device connects **to our server** (Target IP + Target port, e.g. port 8888). Set in the web page `http://<device-ip>` (password `123456`), then **Submit AND Reboot** (Submit alone doesn't apply).
- Don't open the web page during operation; it pauses communication until the next reboot.
- Web page buttons: **Reboot** = safe restart (all data kept, tested); **Submit** = save network settings (then Reboot); **Restore** = probably factory network settings (`192.168.3.7`, TCP Server) → device stops reaching the server until reconfigured. Steps to get back in: `DEVICE-NOTES.md` → "Web page buttons".
- The server's IP must not change (reserve it in the router / use DNS), or the device can't find the server. (Happened 2026-10-03: the PC's DHCP address changed from .7 to .3 and the device lost the server.)
- DNS server (web page) is only used when the Target is a domain name. Factory value `114.114.114.114` (China); for production with a domain use the router (e.g. `192.168.1.1`) or `8.8.8.8`.
- ✔ Reconnects by itself 1–10 s after a server restart or a power cut. It sometimes opens two connections: keep the newest.

---

## 2. Wire protocol

### 2.1 Frame format ✔ (differs from the manual)
Frames travel as **ASCII hex text** (two characters per byte, uppercase), not binary. Binary frames get no reply.

```
Head(1) | ID block(8) | Checksum(2) | Length(2) | Serial(4) | Cmd(2) | Type(1) | Status(1) | Data(N)
  FA/AF   FFFFFFFFFFFFFFFF  sum         N           BB900021
```
- **Head:** `FA` = sent by the server, `AF` = sent by the device. The server's replies to device messages also use `FA`.
- **ID block:** 8 bytes `FF`, not in the manual. The device ignores our frames without it.
- **Checksum:** 16-bit sum of all bytes from **Length to the end of Data**, `& 0xFFFF`. (It does **not** cover the head or the ID block.)
- **Length:** number of Data bytes only.
- **Serial:** the device serial (`BB900021`). Frames with another serial are silently ignored.
- **Type:** `01` = request from the server (we always use `01`), `02` = response, `00` = device message (heartbeat), `03` = device event (0215).
- **Status:** `00` in requests; in responses `00` = OK, other values per command.
- All multi-byte numbers are **big-endian**.

Example from the logs, server asks for the counts (0202), sent as this text:
```
FAFFFFFFFFFFFFFFFF01710000BB90002102020100
FA | FFFFFFFFFFFFFFFF | 0171 | 0000 | BB900021 | 0202 | 01 | 00
checksum 0x0171 = 00+00 + BB+90+00+21 + 02+02 + 01 + 00
```
Device reply: `AFFFFFFFFFFFFFFFFF01820008BB900021020202000000000700000001` (users 7, records 1).
TCP is a stream: reassemble using Length; resync on `FA`/`AF` if a checksum fails.

### 2.2 Messages the device sends by itself, and our required replies
| Cmd | When | Data | Server must reply |
|---|---|---|---|
| **0101** heartbeat | every **60 s** (every **1 s** while unanswered) | 7-byte BCD clock `ss mm hh wd DD MM YY` + `BB` | `FA … 0101 Type 02`, no data ✔ |
| **0214** door record | the moment the door opens / a scan is decided; also all un-sent records after connecting (1 per second) | one 16-byte record (§6) | `FA … 0214 Type 02`, no data ✔. The device waits for it before sending the next |
| **0215** access request | online mode: every QR/card/PIN scan | `50` + QR text (QR) | decision (§3) |
| 0109 door sensor | door opened/closed (not tested) | `01`/`00` | ack, else repeats every 5 s |
| 0108 doorbell | room number + `#` (not tested) | `90` + room | `01` open / `00` don't |

⚠ **Never reply to batch commands 0210 / 0211 / 0505.** Our reply is not accepted, and for 0505 the device re-sends the batch immediately on every reply → endless loop → the device's network part reconnected (2026-10-03).

---

## 3. Online mode (QR mode 0602 = `02`) — server decides ✔

### Flow
1. Member scans a QR. The device sends **0215** with data `50` + the **QR text as-is** (any text: our encrypted QR, a short token, even a website URL).
2. Server checks the content (member, membership, QR age, etc.).
3. **Allow:** reply `FA … 0215 Type 02 Status 00`, then **~0.3 s later** send **0201 unlock** with the open time in seconds (e.g. `05`).
   **Deny:** reply `FA … 0215 Type 02 Status 01` and send nothing else.
4. The device opens, beeps twice, and sends a **0214** record type `70` ("remote open"), card `00000000`.

### Rules ⚠
- **0215 status 00 alone does NOT open the door.** Only 0201 opens it.
- Don't send 0201 in the same instant as the 0215 reply; it gets ignored. ~0.3 s gap works.
- **0201 opens the door whenever it arrives**, it isn't tied to the scan. A late "allow" (tested 73 s later) still opens the door → answer fast; never send an old allow after a timeout.
- The device asks **once**. No answer → nothing happens (no beep, no retry, no deny).
- **Server down / not connected → scans do nothing and are lost** (not sent later, not stored). This holds even for a valid device-compatible encrypted QR of a member registered on the device (tested with the cable unplugged and with the server stopped): **online mode has no local fallback.**
- Scans while the door is still open are still sent ✔ → we get every scan for attendance.
- The device user list is **not used** in online mode. No users need to be on the device.
- **Attendance = from 0215 content** (the member). The 0214 record only says "remote open".
- The QR content is free: a **short token** (e.g. `GW:1:8F3A2C`, 11 chars) scans much faster and from smaller screens than the 152-char encrypted QR ✔. Keep content short (< ~50 chars).
- Member feedback: 2 beeps + door opens on allow; on deny the door stays shut. "Why denied" must come from the app.

---

## 4. Offline mode (QR mode 0602 = `01`) — device decides ✔

The device decrypts and checks the QR itself. Works without the server. Every scan is still reported as a 0214 record with the member's card number when connected.

### 4.1 Requirements
1. **QR key** loaded with **0601** (data = 32 hex characters as ASCII text, e.g. key `FF20ADBC…238E`).
2. **Encryption:** RC4 using the key's **32 ASCII characters** as the RC4 key ("ascii32"); the QR content is the result as **uppercase hex text** (152 chars). With the 16 raw bytes as key the device doesn't react at all.
3. **The QR's card ID must be a card number in the device's user list** (0501/0504). Otherwise refused.

### 4.2 QR content (76 bytes before encryption)
| Field | Bytes | Value | Checked offline |
|---|---|---|---|
| Header, type, length | 4 | `2618` `21` `48` (fixed) | ✔ |
| **Card ID** | 4 | member's card number (must be in the user list) | ✔ |
| Device SN | 4 | `BB900021` | ✖ **ignored** (tested) |
| Card type | 1 | `01` (IC card) | – |
| Lift user ID | 2 | `FFF1` (not used) | – |
| Lift permission groups | 12 | `FF`×12 | – |
| Door permissions | 32 | bitmap, last byte bit 0 = door 1 → `00…0001` | ✖ **ignored** (door-2-only QR opened) |
| Access time, reserve | 2 | `FF FF` | – |
| **Account validity** | 4 | expiry, Unix time, **in device time** (§4.4) | ✔ to the second |
| **Use limit** | 1 | `00` unlimited, `01`–`09` | ✔ counted **per QR** |
| QR valid from | 4 | Unix time | ✖ **ignored by this firmware** |
| QR duration | 2 | minutes, < 2880 (`0B40`) | ✖ **ignored** |
| CRC32 | 4 | over all fields above; custom CRC32 (poly `04C11DB7`, init `16E008EC`, 32-bit little-endian words) | ✔ |
Reference implementation: `tools/tcp701-tester/protocol.py` (`qr_plain`, `qr_crc32`, `rc4`, `qr_encode`). Test vector: spec example CRC = `802916C8`.

### 4.3 What the device checks offline ✔
| Check | Result when it fails |
|---|---|
| Key/format wrong, or CRC wrong (forged/tampered QR) | no reaction (no beep), nothing logged |
| Card ID not in user list | 3 beeps, door shut, 0214 type `50` state `FF` + card |
| Account validity passed | 3 beeps, door shut, **nothing logged** |
| Use limit reached (per QR) | refused, **nothing logged** |
| QR valid-from / duration | **not checked** (even with time-limit 0204 on) |
| Device SN, door permission | **not checked** → a QR for another device with the same key opens this one. **Use a different key per device.** |

Accepted: door opens, 0214 type `50` state `EC` + card number.

### 4.3a Keys: one per building
- Offline security rests on the **QR key** (+ user list, account validity, use limit). Forged or tampered QR codes are ignored.
- The device ignores the serial and door inside the QR, so **every device with the same key accepts the QR**.
- Approach: **one key per building** (one QR works at all its doors), **different keys per branch/gym**. Each device still needs the members in its own user list.
- ❓ "Use once" is most likely remembered per device → a single-use QR may work once at each door. Keep validity short.
- Key leaked → load a new key (0601) on all devices that used it; old QR codes stop working (❓ to confirm: test 3.18).
- The QR still carries the device serial: fill it in (the server checks it in online mode), even though the device ignores it offline.

### 4.4 Time zone ⚠
The device treats its own clock as **China time (UTC+8)**. Its clock is set to local time (India, UTC+5:30), so it thinks "now" is 2½ h earlier.
→ Write all QR timestamps as **real Unix time − 9000 s** (in general: real time + local UTC offset − 8 h).
Proof: account expired 2h15 ago → opened; 2h45 ago → refused.

### 4.5 Short-lived, single-use offline QR ✔
Because the QR window is ignored, use the **account-validity field as the timer**:
- account validity = real time − 9000 s + **N minutes** (e.g. 2–3)
- use limit = `01`
Tested: a 2-minute QR opened immediately and was refused after 2 minutes. A used QR is refused; a new QR for the same member works (each QR differs because its timestamps and CRC differ).
- Limit 1 stops reuse; short validity stops unused QR codes (screenshots, sharing, stockpiling) working later.
- ❓ How many used QRs the device remembers, and whether a power cut resets that memory: unknown → keep validity short anyway.
- Two QRs for the same member created in the same second are identical (treated as one).

### 4.6 Outages in offline mode ✔
- With the network cable unplugged, offline QR codes still open the door.
- On reconnect the device **uploads the records made during the outage by itself** (0214, ~1 per second, real scan times). **Only records not yet acknowledged** are sent, not the whole history. Ack and deduplicate as usual; a 0213 read-back from the last known record number is a safety net.
- A pulled cable does **not** close the TCP connection on the server side. Detect "offline" by missing heartbeats (expected every 60 s; e.g. none for 2–3 min).
- Members still need a QR from the backend during an outage: works if only the gym's network is down (members on mobile data); if the backend itself is down, plan a fallback (e.g. one longer-valid emergency QR in the app, or staff unlock).

### 4.7 Online vs offline at a glance
| | Online (02) | Offline (01) |
|---|---|---|
| Who decides | server | device |
| Works when server is down | ✖ scans lost | ✔ (records uploaded automatically on reconnect) |
| Users needed on device | none | every member's card number |
| QR content | anything (short token) | 152-char encrypted vendor format |
| Member identity in 0214 record | ✖ (type 70, card 0) | ✔ (type 50 + card number) |
| Instant block of a member | ✔ | after their last QR expires, or delete their card |
| Device can switch mode itself | ✖ (only via 0602 from the server) | |
| Mixed (local first, then server) | ✖ not available for QR. 0106 mixed is for cards/PINs only (tested: unknown QR refused, not forwarded) | |

---

## 5. User management

### 5.1 User record (16 bytes) — used by 0501, 0504, 0505
| Bytes | Field | Notes |
|---|---|---|
| 1–4 | **Card number** | what QR codes and records refer to |
| 5–8 | PIN | **must be unique** (duplicate PIN → status 2, even `00000000` can be used only once). PINs may open the door from the keypad → use untypeable values (e.g. `FFFFFFxx`) ❓ keypad length limit |
| 9–10 | **User ID** | device's internal handle, used only to delete (0502 type 03) |
| 11 | Time group | `00` = no restriction |
| 12 | Days | bit per weekday, `7F` = every day |
| 13–14 | Daily from | minutes after midnight (`0000`) |
| 15–16 | Daily until | minutes (`059F` = 23:59) |
Example: `000000A0 00000000 00A0 00 7F 0000 059F`.

**Staff PIN users (decided 2026-10-03):** only a few people get a PIN, with **unlimited access** (always `00 7F 0000 059F`: no group, every day, 00:00–23:59). The PIN is the typed number in hex (654321 → `0009FBF1`). To change a PIN: delete the whole user (0502 `03` + user ID + `0000`), then add it again. The keypad works with the server off; type 21 records carry the typed PIN, so the server keeps a PIN → person list.

### 5.2 Commands ✔
| Action | Cmd | Data | Reply |
|---|---|---|---|
| Add one | 0501 | 16-byte record | `00` OK, `01` dup card, `02` dup PIN, `03` dup user ID |
| Add up to 16 | **0504** | count (1 byte) + count×16 bytes | `00` OK, instantly |
| Delete card only | 0502 | `01` + card (4) | `00`; entry (user ID + PIN) stays |
| **Delete whole user** | 0502 | `03` + **user ID first**, padded: `0300B30000` | `00`; (`03000000B3` fails) |
| Delete by PIN | 0502 | `02` + PIN | `00` / `01` not found |
| Erase all users | **0503** | — | `00` after **~20 s** |
| Read all users | 0505 | — | all slots, 16 per batch; ⚠ **don't reply** |

### 5.3 Slots and counts ⚠
- A deleted user leaves an **empty slot** (all `00`) that is **not reused**; new users go after it. The user count (0202) counts slots and never goes down.
- → Over time joins/leaves use up the 20,000 slots. **Full reset works** ✔: 0503 erase all → 0504 re-add active members (16 per command) → count = exact number of users, empty slots gone.
- Alternative design (idea, not tested in production): a **pool of fixed slots** loaded once (card number = user ID = slot number, 1:1); the server maps slot ↔ member and never touches the device on join/leave. Needs short-lived single-use QR codes.
- The device shipped with one user: card `3FE6F236`, PIN 11111112, 08:30–17:30 → remove before go-live.

---

## 6. Door records

### 6.1 Record (16 bytes) — 0214, 0213
```
Type(1) State(1) Extra(4) Card(4) Time(6: YY MM DD hh mm ss, BCD)
50 EC 00000000 000000B2 261002180849  = QR, accepted, card 000000B2, 2026-10-02 18:08:49
```
- Type: `50` QR (offline), `70` remote open (0201 / online QR), `80` exit button, `21` keypad PIN, `10` card.
- State: `EC` accepted/normal, `FF` refused. (`EC` stays after upload; it isn't "new/unsent".)
- Extra: always `00000000` in our tests (no QR field shows up here).
- Time: device clock (local wall time as set with 0103). ⚠ After the 2026-10-03 crash the **record time was wrong** (hour −4, minutes garbled) while the heartbeat clock was right, and Sync time didn't fix it. → For live records use the **server's receive time** (they arrive within ~1 s); compare with the record time and flag big differences (a sign of a damaged device). On the test device it recovered by itself hours later, after another Sync time (0103) and restarts → the recovery routine should re-sync the clock and re-check the record time.

### 6.2 Getting records
- **Live (0214)** ✔: every door event, within ~1 s. Ack each one. Records not yet sent (e.g. made offline) are pushed after (re)connecting. ⚠ The same record occasionally arrives twice → **deduplicate** (type + card + time).
- **Full history: 0213 one by one** ✔ — data = 2-byte record number from `0000` (oldest); past the last record the device returns all `FF`. ~50 ms each. (0211 batch read is unusable: only the first 8, no reply format accepted.)
- **0210** (new records) on an empty log: no reply. Not tested with data.
- **0212 erase all records**: `00` after **~15 s**.
- The device keeps every record even after sending it live ✔. No records were lost in a power cut ✔.
- ❓ What happens at 60,000 records (overwrite oldest or stop) is undocumented.

### 6.3 Counts (0202) ⚠
Reply 8 bytes: users (4) + records (4). **Unreliable:** too low right after a power-up (e.g. 5/106 instead of 6/121), and the user count includes deleted slots. Don't use it for logic; use the server's own data, or 0213 / 0505 to verify.

---

## 7. Door control
- **0201 unlock** ✔: data = seconds to stay open (`05` = 5 s). `00` = use the 0203 time (works when sent on its own). Always a type-70 record.
- **0203 relay hold time** ✔: data = seconds (`03`), `FF` = toggle mode (not tested). Used by 0201 `00` (and probably by offline opens/exit button ❓). Doesn't override 0201's own seconds.
- ❓ A second unlock while the door is open: whether it extends the open time wasn't checked.
- Exit button opens the door locally (type `80` record) ✔.

---

## 8. Time
- **0103 set clock** ✔: 7 bytes BCD `ss mm hh wd DD MM YY` (weekday Mon=01 … Fri=05, Sat=06 seen; Sun=07 assumed), local wall time.
- The clock **survives power cuts** (battery) ✔ but **falls behind**: ~1–2 s per reconnect + a few s/hour (−8 s after 2.5 h).
- → Re-sync with 0103 **on every connect** and periodically (e.g. hourly). Matters for offline QR validity.
- The device interprets its clock as UTC+8 for QR timestamps (§4.4).

---

## 9. Reliability rules for the server
0. ⚠ **Never hard-code the device serial.** On 2026-10-03 a key load (0601) got no reply, a power cut followed, and the serial became `FFFFFFFF`; commands with the old serial were silently ignored. Use the serial from the device's own frames (every heartbeat), and identify devices also by their connection (e.g. the network module's **registration packet** = custom ID sent on connect). Do settings writes (0601, 0602, …) only with stable power, wait for OK, verify.
1. **One command at a time per device**; queue the rest.
2. **Per-command timeouts:** ~5 s normally; erases are slow (0212 ~15 s, 0503 ~20 s with little data — likely longer when full) → allow minutes, and **accept late replies**.
3. A timeout = **unknown**, not failed. Verify by reading back (0213 / 0505) instead of resending; never auto-resend adds.
4. Never send a late "allow"/0201 after the decision window.
5. Never reply to 0210 / 0211 / 0505 batches.
6. Always ack 0101 and 0214 (otherwise they repeat every 1 s / block the next record).
7. Deduplicate 0214 records.
8. Re-sync the clock on connect.
9. In online mode, scans during a server/network outage are lost → plan a fallback (offline mode, staff unlock).
10. Back up users (0505) and records (0213) before any erase.

---

## 9a. Device reset: detection and recovery from the server
**What happened (2026-10-03):** a QR-key load (0601) got no reply, then a power cut. After restart the device had lost **its serial (now `FFFFFFFF`), the QR key and all users**; records were empty and **record timestamps were wrong** (scans at 14:07 stamped 10:04), while the heartbeat clock was right. Offline QR mode survived. Treat this as "the device can lose its settings and user list at any time".

**Fixing a wrong serial:** the vendor command `FA FF×8 <checksum> 0008 <current serial> 0000 01 00 AFFFAC88 <new serial>` (cmd `0000`) rewrites it (tested 2026-10-18, `FFFFFFFF` → `BB900021`). The server must know the intended serial per device (e.g. from the registration packet or its own table).

**Keep the desired state on the server** (the device can't be trusted to keep it):
- QR key per device (0601), QR mode (0602), card/PIN mode (0106), relay time (0203), time-limit (0204), heartbeat interval (0205)
- the full user list for that device (pool slots or members), as 16-byte records

**Detect a reset** (check on every connect, and again a minute later because counts read too low right after power-up):
1. **Serial changed** (e.g. `FFFFFFFF`) compared with what this connection/registration ID had before.
2. **User list differs**: read all users (0505, **no reply to the batch**) and compare with the server's list. Don't rely on 0202 alone.
3. **Offline refusals of known members**: 0214 records type `50` state `FF` for card numbers the server knows are loaded.
4. **Record time far from the receive time** (more than a few minutes off).
5. A settings command that got **no reply** (0601 etc.) → state unknown.
(The device has no command to read back the key or modes, so "key lost" can only be inferred from 3, or prevented by re-applying.)

**Recovery routine (idempotent; run it after any detection, or when a device is new):**
1. Use the serial from the device's own frames for all commands.
2. **0103** set the clock.
3. **0601** load the key → wait for OK (allow a few seconds; if no reply, wait, then verify by repeating, don't proceed blindly).
4. **0602** QR mode, **0106**, **0203**, **0204**, **0205** as stored.
5. **0503** erase all users (slow, ~20 s+) → **0504** re-add all users, 16 per command, each waiting for OK.
6. **Verify:** 0505 user list matches; 0202 count matches (after the device has been up a while); a test scan if staff are present.
7. Mark the device healthy only after the verification; log the event.
**The 0601 key write itself hung the device** (no reply, then no heartbeats for 6 minutes). So: load the key **only when it changes**, never on every connect; after any settings write, **watch the heartbeats**: if they stop, the device has hung → alert / power-cycle, then run this routine.
Only run it with **stable power**, one command at a time, never in parallel with other commands. Records made before the reset that weren't acknowledged may be lost; the server's own copy of live records is the reference.

## 10. Open questions (asked or to ask the vendor — see `VENDOR-QUESTIONS.md`)
- Correct reply for batch uploads 0211 / 0210 / 0505 ("88 bytes"?).
- Why the QR valid-from/duration is ignored offline; which time zone the firmware uses.
- Whether deleted user slots are ever reused; official format of 0502 type 03.
- Untested: card entry (0106 online/offline/mixed), keypad PIN length, door sensor 0109, doorbell 0108, heartbeat interval 0205, relay toggle `FF`, beep 0102, device validity dates 0104/0105, behaviour at 60,000 records, used-QR memory size.

---

## 11. Test device state (2026-10-03)
- QR mode **offline** (01), time-limit off (02), QR key `FF20ADBC…238E` (test key — replace for production).
- 7 users: original `3FE6F236` + test cards `000000A0`, `000000B1`, `000000B2`, `000000B3`, `000000C1`, `000000C2` (user IDs `00A0`… = last byte of the card; PINs `FFFFFFxx`, A0 has PIN 0).
- Records erased on 2026-10-03; backup in `tools/tcp701-tester/logs/records-20261003-122350.json`; users backup `device-users-20261003.json`.
- Test tool: `tools/tcp701-tester/` (dashboard `http://localhost:8000`, phone page `/static/phone.html`).
