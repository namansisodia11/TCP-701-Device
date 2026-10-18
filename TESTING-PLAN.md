# TCP-701 Testing Plan (live checklist)

Tick items as we go (`- [x]`) and write results after **→**. Confirmed answers go back into
`.claude/skills/tcp701-protocol/SKILL.md` §10. Tool: `tools/tcp701-tester/` (see its README).

Legend: 🔧 build task · 🧪 test on device · ⚠ destructive (backup first) · `[x]` done · `[~]` partly done

**Device:** SN → BB900021 (from heartbeat) · Network module → Ebyte EBT3001 fw 9013-2-17 · MAC → 0C-3D-5E-93-75-E0 · IP → 192.168.1.50, TCP Client → PC 192.168.1.7:8888
**Tested by / date:** Naman · first session 2026-09-30 21:25–21:48 (log `session-20260930-214022.jsonl`)

---

## ⭐ Feature checklist (gate access): the main plan
Test **one feature at a time**, from a gym-gate point of view. "It works" is enough; no deep edge cases.
The detailed protocol items further down are **optional** reference.

**Member entry**
- [x] F1 Member with a valid QR gets in (online, server allows) → ✔ opens via 0215 + 0201 (2026-09-30 / 10-02)
- [x] F2 Bad QR refused (expired, not started yet, wrong key, other device, wrong door, account expired) → ✔ all denied, no open (2026-10-02)
- [x] F3 Short token QR (e.g. `GW:1:8F3A2C`, 11 chars) → ✔ scans easily and is forwarded as text (2026-10-02). Opening uses the same server path as F1 (0215 + 0201), so not re-tested.
- [x] F4 Door open time adjustable → ✔ 0201 seconds (1/2/5 s), or `00` = the 0203 time (2026-10-02)
- [x] F5 Quick back-to-back scans, **including scans while the gate is still open** → every scan reaches the server (we need ALL QR data for attendance), no stuck state → ✔ (2026-10-02 12:50) 3 scans in 6 s, while the door was still open from the previous one: **every scan reached the server**, each was allowed and re-unlocked, and each made its own record. 12:51–12:54: 13 more scans 2–3 s apart, all received and allowed; 10 s open time applied from 12:52.

**Leaving & staff**
- [x] F6 Exit button lets people out (no server needed) → ✔ tested by Naman; the device stored 28 exit-button records (type 80) by 2026-09-30
- [x] F7 Staff open the door remotely (dashboard Unlock) → ✔ 0201 (2026-09-30)
- [x] F8 Member feedback: what the member sees/hears on allow vs deny (beeps / LED) → ✔ (Naman) The device only forwards the QR to the server. Valid scan = **2 beeps** + gate opens. Denied = gate stays shut. No other on-device message. **Re-checked 2026-10-03 20:44 (Naman):** offline valid = 1 beep, offline invalid = **3 beeps**; online valid = 1 beep, online invalid = **1 beep** too (same as valid, so the member can't tell). Tried the server sending 0102 beep ×3 after a deny (tool option "Beeps on deny"): works only sometimes. Not important, dropped.

**Outages & reliability**
- [x] F9 Server down → ✔ no entry, scans lost (not sent or stored later) (2026-10-02)
- [x] F10 Device power cut / network cable out → reconnects by itself, settings + QR key kept → **Power cut ✔ (2026-10-02 ~13:02):** reconnected by itself (13:02:48), online QR mode kept, clock kept (still −8.6 s, so it has a battery-backed clock), scans work right after. Scans made **while it was booting / not yet connected are lost** (observed by Naman), same as server down. **Network cable ✔ (2026-10-03):** reconnects by itself; online mode → scans lost meanwhile; offline mode → keeps opening and uploads the missed records on reconnect.
- [x] F11 Backup entry during an outage: offline QR mode (0602 = 01) and/or keypad PIN → ✔ **Short-lived offline QR works (18:19)**: account validity = real time − 2.5 h + N min (device uses UTC+8). Earlier: ✔ **Offline QR works (17:43)**: ascii32 key + hex text, AND the QR's user ID must be a card number in the device's user list (added `000000A0` with 0501). The device logs type 50 + member ID (EC accepted / FF refused). **The QR time window is NOT enforced** (17:53: 5-min QRs for now, 2.5 h ago and 5.5 h ahead all accepted). Still to check: account expiry, use limit, 0204 time-limit switch; works with the server stopped. 
- [ ] F12 Clock stays correct (it falls behind ~8 s in 2.5 h, ~1–2 s per reconnect) → server re-syncs on connect + daily → Device side known (sync 0103 works, drift measured). What's left is server work (auto re-sync), not a device test (Naman, 2026-10-03).

- [x] F21 Keypad PIN entry (backup way in) → ✔ (2026-10-03 20:00) right PIN opens, wrong PIN refused, each try is reported live as a type 21 record that carries the **typed PIN** (not the member's card number). See 4.4. **Server off ✔**: PIN still opens; the record (20:03:55) was uploaded when the server came back (20:04:11). **Delete ✔**: after 0502 `0300D10000` the old PIN is refused (`21FF` 20:08:42, 20:08:51). No PIN-change command: delete the whole user + add again.

**Records**
- [x] F13 Every entry is reported to the server (0214), duplicates ignored → ✔ reported live; only unacknowledged records are re-sent after a reconnect (2026-10-03). Duplicates do occur (2026-10-02) → the server must deduplicate (implementation requirement).
- [x] F14 Read the stored entry history from the device (0211) → ✔ via **0213 one by one** (0211 batches can't be acked). 75 records, all live records present, nothing lost. Tool button: Commands → Download all records. Earlier notes: Works: batches of 8, oldest first, each needs our ack. First try got only 8 (tool didn't ack). 13:15 retry with our ack (FA 0211 Type 02, no data): still only 8, so the device wants a different ack (manual: "response is 88 bytes", unclear). Asking again (13:17) returns the same first 8, then the device repeats that batch every 5 s. **Dropped**: the server already gets every record live.

**Offline user-pool approach (to test later)**
- [ ] F18 Load a pool of ~2,000 users with batch add (0504, 16 per command = 125 commands) → time it, check 0202 users = 2,000 (+ existing), spot-check with 0505 / offline QR for a few slots → 
- [ ] F19 Long outage: offline mode, cable unplugged for a longer time, many entries (e.g. 20–50 scans) → reconnect → all records uploaded automatically, none missing (compare with Download all records) → 
- [x] F20 (not needed: the gate stays open during a power cut, so reusing a QR gains nothing. Naman, 2026-10-03) Used-QR memory after a power cut: use a "use once" QR, power-cut the device, scan the same QR again (still within its validity) → refused or accepted? → 

**Optional (only if Gymwale uses them)**
- [ ] F15 RFID card entry · [ ] F16 Door-left-open sensor (0109) · [~] F17 Doorbell (0108) → ✖ not reachable from the keypad (2026-10-03 20:34–20:37): `1234#`, `#`, `#1234#`, `1234` + wait all give **no 0108**; digits + `#` are read as a PIN (`21FF…04D2`). Asked the vendor how to start a room call.

---

## Phase 0 — Network setup & first contact (device = TCP Client → our server)
- [x] 0.1 Power device (9–24 V DC); PC ↔ device on same network (switch/router or direct) → Done. Device at 192.168.1.50 on the same router as the PC (Wi-Fi 192.168.1.7); ping from the PC replied in 2–3 ms.
- [x] 0.2 Start tool: `.venv\Scripts\python app.py` → note PC IP it prints → **192.168.1.7** (Wi-Fi). Ignore 172.23.160.1, which is the WSL virtual adapter. Must be run from `tools\tcp701-tester`.
- [x] 0.3 Allow Python in Windows Firewall (Private) for inbound 8888 + 8000 → An existing Python allow rule covers it (the Wi-Fi profile is **Public**). Proven by the device connecting in on 8888.
- [x] 0.4 Device web UI: Work mode **TCP Client**, **Target IP = PC IP**, **Target port 8888**, device IP on same subnet, module heartbeat/registration **OFF** → Submit → **power-cycle** → Done at `http://192.168.1.50` (device was already on 192.168.1.x). Changed only Target IP 192.168.3.3 → **192.168.1.7**. Everything else was already right (TCP client, port 8888, registration/keepalive off, short connection off). Submit, then Reboot. Reboot is required, because Submit alone doesn't apply the settings.
- [x] 0.5 Dashboard LED green "device connected from …" → 2026-09-30 21:31 connected from 192.168.1.50. First try: no replies because the tool sent binary. Fixed: the device uses ASCII hex + an 8-byte ID block.
- [~] 0.6 Test wiring: lock/LED on relay COM+NO, exit button OPEN–GND, door contact MC–GND → Lock on relay ✔ (0201 opens it), exit button ✔ (type 80 records). Door contact not wired/tested.

## Phase 1 — Core tool: protocol + live traffic viewer
- [x] 🔧 1.1 `protocol.py` codec, decoders, `describe()`
- [x] 🔧 1.2 `tests/test_protocol.py` golden frames pass
- [x] 🔧 1.3 `device.py` TCP link, reassembly, JSONL log, request/response, raw send
- [x] 🔧 1.4 `mock_device.py` fake device
- [x] 🔧 1.5 `app.py` + dashboard (connection bar, live traffic table, raw sender)
- [x] 🧪 1.6 Dashboard works against `mock_device.py`; traffic both directions; export JSONL → API/WebSocket level verified 2026-09-30: connect, auto-identify (SN 00000457), request/response, bad checksum flagged, auto-ack heartbeat, 0215 events, export, probe. Server mode also verified with `mock_device.py --connect` (TCP Client). **Still to do: click through in the browser.**
- [x] 🧪 1.7 Real device connects in (TCP Client) and 0001 → SN → 2026-09-30: no reply. **2026-10-02: answers `BB900021`** on every connect, once the tool uses ASCII + the ID block.
- [x] 🧪 1.8 0002 version → **0004** · 0202 users/records → **1 user, 32 records**. The reply is 8 bytes (4+4), not the spec's 2+2.
- [ ] 🧪 1.9 Type 00 vs Type 01 request — both get a reply? → 
- [ ] 🧪 1.10 Wrong serial in header — rejected or answered? → 
- [ ] 🧪 1.11 Bad checksum ignored? Two frames in one TCP write both answered? → 
- [x] 🧪 1.12 Passive listen 5 min — who sends 0101, interval, exact bytes → The **device** sends 0101 (Type 00): `AF FF×8 ck 0008 BB900021 0101 00 00 <7-byte BCD clock> BB`. While **unacked** it repeats every **1 s**; once acked it comes every **60 s** (9 heartbeats at exactly 60 s gaps, 21:40–21:48). Our ack `FA … 0101 Type 02` is accepted.

## Phase 2 — Door, events, auto-replies
- [x] 🔧 2.1 "Door & events" tab: unlock, beep, sync time, relay delay, open mode, online/offline mode
- [x] 🔧 2.2 Auto-reply toggles (0101/0109/0108/0214/batches) + 0215 policy (manual / allow-status / deny-status / allow-0201) + pending list
- [ ] 🧪 2.3 Beep 1/2/3 (0102) → 
- [x] 🧪 2.4 Sync time 0103; weekday numbering → Works. Byte order sec·min·hour·weekday·day·month·year; Friday = `05`. **Clock falls behind**: ~8 s in 2.5 h after the sync, ~1–2 s lost per reconnect → re-sync on connect. Weekday: Mon = 01 … Fri = 05, Sat = 06 (seen).
- [x] 🧪 2.5 Unlock 0201 `00` and `05` — relay duration correct → `01`, `02`, `05` open for that many seconds. `00` sent alone opens for the 0203 time (3 s). `00` in the same instant as a 0215 reply is ignored.
- [~] 🧪 2.6 Relay hold 0203 `03`, toggle `FF`, restore → `03` OK, used by 0201 `00`; ignored when 0201 carries its own seconds. `FF` not tried.
- [ ] 🧪 2.7 Heartbeat interval 0205 `000A` → 10 s; stop acking 3 → uploads pause → (Default interval already observed: **60 s**. 0205 itself not tested yet.)
- [ ] 🧪 2.8 Door contact open/close → 0109 every 5 s until acked → 
- [ ] 🧪 2.9 Doorbell (room + `#`) → 0108; reply `01` opens → 
- [x] 🧪 2.10 Exit button → opens, log type 80 → ✔ (tested by Naman; 28 type-80 records on the device)

## Phase 3 — QR codes (main focus)
- [x] 🔧 3.1 QR functions: `qr_plain`, `qr_crc32` (test `802916C8`), `rc4`, `qr_payload`, `qr_decrypt`; key format raw16/ascii32; content hex_text/binary; tamper options
- [x] 🔧 3.2 QR tab: key gen, "Load key (0601)", 0602 switch, form, big QR, plaintext breakdown
- [x] 🔧 3.3 Presets Valid / Expired / Future start / Wrong SN / Bad CRC / Wrong key / Limit 1 + scan-result logger
- [x] 🔧 3.4 Phone view `http://<pc-ip>:8000`

**Offline QR (0602 = `01`)**
- [x] 🧪 3.5 Sync time 0103 first → ✔ synced before the offline tests (2026-10-02 13:53 and 17:51).
- [x] 🧪 3.6 Generate key, load via 0601 → status → ✔ status 00 (key `FF20ADBC…238E`).
- [x] 🧪 3.7 Valid QR (door 1, now, 5 min) opens? If not, try raw16↔ascii32, hex_text↔binary. **Working combo** → ✔ **ascii32 key + hex text** (raw16 + hex text: no reaction; binary not tried). Also needs the card number in the user list (0501).
- [x] 🧪 3.8 Log record type `50` appears (0214 / 0210) → ✔ 0214 type 50 + card number; state EC accepted, FF refused (unknown member).
- [x] 🧪 3.9 Expired → denied → ✖ **NOT denied**: the QR start/duration window is ignored (window ended yesterday still opened, also with 0204 on). Use account validity as the timer instead.
- [x] 🧪 3.10 Future start → denied → ✖ **NOT denied** (QR starting 5.5 h later opened). Same cause as 3.9.
- [x] 🧪 3.11 Wrong device SN → denied → ✖ **NOT denied**: QR for `BB900022` opened (registered member B2, 2026-10-03 13:40). Use a different key per device.
- [x] 🧪 3.12 Bad CRC → denied → ✔ ignored silently (no beep, no record), 2026-10-03.
- [x] 🧪 3.13 Wrong key → denied → ✔ ignored silently (no beep, no record), 2026-10-03.
- [x] 🧪 3.14 Wrong door bit (door 2 only) → denied → ✖ **NOT denied**: opened door 1 (2026-10-03).
- [x] 🧪 3.15 Use limit 1 → 1st opens, 2nd denied → ✔ (counted per QR; a new QR for the same member works).
- [x] 🧪 3.16 Account validity in past → denied → ✔ refused, 3 beeps, no record. Checked to the second, in UTC+8 (write times −9000 s).
- [~] 🧪 3.17 Scan distance / angle / brightness limits → Short QR (21×21) scans easily; the 152-char encrypted QR only when shown large. No formal distance test (not needed).
- [x] 🧪 3.18 Change key (0601) → old QRs denied → covered by 3.13: after a key change, old QRs are "wrong key" QRs, and those are refused.

**Online QR (0602 = `02`) — server decides (Access tab)**
- [x] 🧪 3.19 Scan → 0215 16-byte `50…` payload; decoded fields → Not 16 bytes: the device forwards `50` ("P") + the **whole QR text** (152 hex chars = our 76-byte encrypted record). The server decrypts it, and all fields and the CRC check out.
- [x] 🧪 3.20 allow-status opens? deny-status denies? allow-0201 opens? **Grant method** → 0215 status 00 alone does **not** open. 0201 sent 0.3 s after it **opens** (grant = both). Deny: 2026-10-02 10:36–10:37 the phone presets Expired, Future start, Wrong key, Wrong SN, Door 2 only and Account expired were each **denied by the server rules with the correct reason**. Status 01 was sent, no 0201, and no door-open record was created.
- [x] 🧪 3.21 No host reply → timeout behaviour → Device does **nothing**: no beep, no retry, no deny. A late Allow (73 s) still opens, via 0201. **Server stopped** → scan does nothing and the door stays shut. When the server comes back the missed scans are **not** sent and **not** stored (record count stayed 53).
- [x] 🧪 3.22 Random plain-text QR in online mode — what is forwarded? → ✔ forwarded as-is: `50` + the text (website URL, `GW:…` tokens).

## Phase 4 — Users, cards, logs
- [ ] 🔧 4.1 "Users & logs" tab (add/temp/delete/batch/counts/logs; confirm on destructive)
- [x] 🧪 4.2 Backup: 0505 users + 0211 logs saved → ✔ users: 0505 first batch (`device-users-20261003.json`; never ack it). Logs: 0213 one by one (Download all records).
- [ ] 🧪 4.3 Card user + swipe → opens, log 10; UID byte order matches physical card? → 
- [x] 🧪 4.4 PIN user → opens, log 21 → ✔ (2026-10-03 20:00) user D1 with PIN 654321 (0501 `000000D10009FBF100D1007F0000059F`, OK). Right PIN opened twice (`21EC0009FBF1…`), wrong PINs refused (`21FF…`). Checked on the device, no server question, also with QR in online mode.
- [~] 🧪 4.5 Duplicate card/PIN/ID → status 1/2/3 → PIN duplicate = status 2 ✔ (0501, 2026-10-02). Batch add 0504 (2 users) OK ✔ (2026-10-03). 
- [ ] 🧪 4.6 Temp user expiring in 2 min → works then fails → 
- [x] 🧪 4.7 Delete by card / PIN / ID (0502 type 1/2/3); type-3 data layout → ✔ type 1 removes the card only; type 3 needs the user ID first (`0300B30000`; `03000000B3` fails); type 2 returns status 1 when the PIN isn't found.
- [ ] 🧪 4.8 Open modes 0107 `01`/`02`/`03` → 
- [~] 🧪 4.9 Time limit 0204 + group 1 window excluding now → denied; weekday mask bit order → 0204 on/off works (OK) but doesn't affect QR windows. User time groups / weekday mask not tested.
- [~] 🧪 4.10 0106 offline/online/mixed; unknown card → 0215 `10`+UID → 0106 = 02 OK; it does **not** apply to QR (unknown QR refused, not forwarded). Card behaviour not tested (no RFID test yet).
- [x] 🧪 4.11 Logs: 0210 ×2 (2nd empty), 0211, 0213, 0214; batch ack format → **0214 confirmed**: on connect the device pushed all **32** stored records (count matches 0202), 1 per second, each waiting for our ack (`FA 0214 Type 02`, no data). 28 exit-button (type 80, state EC), 4 PIN (type 21, state **FF**, probably wrong PIN). 0210/0211/0213 not tested yet. **Final (2026-10-03):** 0213 one-by-one reads everything; 0211 unusable (first 8 only); 0210 no reply on an empty log; 0214 live + automatic upload of unacked records after reconnect.
- [x] 🧪 ⚠ 4.12 (optional) 0212 format logs, 0503 format users, restore from backup → ✔ 2026-10-03: logs erased (~15 s), users erased (~20 s), 7 users restored with one 0504; offline QR refused in between and accepted after.

## Phase 5 — Wrap-up
- [ ] 🧪 5.1 (Optional) TCP Server mode: device back to TCP Server, dashboard "connect to device" 192.168.3.7:8887 → 
- [~] 🔧 5.2 Update SKILL.md §10 with confirmed answers → frame format, heartbeat, 0211/0213/0505, offline QR rules and time zone added along the way; no full review yet.
- [~] 🔧 5.3 Archive session logs; summary + recommended Gymwale settings → ✔ summary written: `IMPLEMENTATION-GUIDE.md` (2026-10-03). Logs not archived yet.

---

## Findings log
| Date | Item | Observation | Raw frame(s) |
|---|---|---|---|
| 2026-10-03 | F17 | Doorbell tries on the keypad (reply = open door): `1234#` → PIN 1234 refused (20:34:39); `#` alone, `#1234#`, `1234` + wait → only PIN records (PIN 1 at 20:35:09, PIN 1234 at 20:37:15), **no 0108 ever**. Sending 0108 from the server → no reply, a beep (wrong direction: 0108 is device → server). | `21FF000004D200000000261003203439` |
| 2026-10-03 | F21 | Server stopped ~20:02–20:04: PIN 654321 opened (Naman); record `21EC…200355` pushed at reconnect 20:04:11. Then 0502 `0300D10000` OK 20:08:33 → PIN 654321 refused at 20:08:42 and 20:08:51. | `21FF0009FBF100000000261003200842` |
| 2026-10-03 | 4.4 | 0501 user D1, PIN 654321 → OK 19:59:58. Keypad: 20:00:20 wrong (`0000000C` = 12) refused, 20:00:27 654321 **accepted**, 20:00:34 wrong (`0007FDB2` = 523698) refused, 20:00:40 654321 **accepted**. All arrived live as 0214; no 0215. QR mode was online (0602 = 02). | `21EC0009FBF100000000261003200027` |
| 2026-10-02 | 3.21 | Policy manual: scan at 10:45:47 got no answer and the device did nothing and sent no repeat 0215. Allow at 10:47:00 (73 s later) opened the door (0201 OK + type-70 record). Server stopped at 10:48:44 → scans don't open (observed by Naman). | 0215 @ 10:45:47, 0201 `05` @ 10:47:00 |
| 2026-10-03 | 3.11–3.14 | Offline security checks, registered member B2: Valid opened; **Wrong SN opened; Door 2 only opened** (records `50EC…B2` 13:40:03–13:41:18); Bad CRC and Wrong key: no beep, no record (Naman). Device ignores SN + door; rejects tampered/forged QR. | `50EC00000000000000B2261003134011` |
| 2026-10-03 | F11 | Offline mode, cable unplugged ~13:20:40: B2 accepted 13:20:50 and 13:20:57. Reconnect 13:21:11 → both records pushed automatically 13:21:13 / 13:21:14. Server didn't detect the cut (connection stayed until replaced). | `50EC00000000000000B2261003132050` |
| 2026-10-03 | 4.10 | 0106 = 02 (mixed) + 0602 = 01: B2 (registered) opened locally 12:57:52 (`50EC`); member 00000001 (not registered) refused 12:58:35 (`50FF`), no 0215 to the server. Mixed doesn't apply to QR. | `50FF0000000000000001261003125835` |
| 2026-10-03 | 3.21 | Online mode + device-compatible QR (B2, registered): reaches the server when connected (12:49:36). Ethernet unplugged ~12:50 → scans don't open, nothing stored (records stayed 3), nothing sent after reconnect (12:51:01). Server stopped 12:52 → same. No local fallback in online mode. | 0202 `0000000700000003` |
| 2026-10-03 | 4.12 | After 0503: offline QR B2 refused 12:35:21 (`50FF…B2`). 0504 re-add 7 users (original + A0, B1, B2, B3, C1, C2) → OK immediately; 0202 users **7**, records 1. B2 accepted again 12:36:07. Full reset cycle works. | `50EC00000000000000B2261003123607` |
| 2026-10-03 | 4.12 | 0503 erase all users → OK after ~20 s (12:31:29 → 12:31:49); 0202 users 8 → **0**, records 0. | 0202 `0000000000000000` |
| 2026-10-03 | 4.12 | 0212 erase all logs → OK after ~15 s (12:26:35 → 12:26:51); tool timed out at 3 s (now 30 s). Download all records → 0 records. 0210 on the empty log → no reply. | 0213 `0000` → `FF…FF` |
| 2026-10-03 | 4.5 | 0504 batch add C1 + C2 → OK at 12:25:04; 0202 users 6 → 8. | `0504` count `02` |
| 2026-10-03 | 4.11 | Download all records (0213 one by one) → 121 records, file `logs/records-20261003-122350.json`; all 111 unique live records present, none missing (power cut lost nothing). Manual 0213 with empty data → all FF. 0211 with batch auto-ack off → one batch, no repeat. | `50EC00000000000000B1261002184200` (last) |
| 2026-10-03 | 4.2 | 0505 read users → one 96-byte batch: 6 slots (original card 3FE6F236/PIN 11111112/ID 0012/08:30–17:30, A0, B1, B2, **empty slot** (deleted B3), B3 re-added). Tool auto-acked → device re-sent at once → loop 101× in 8 s → device reconnected 11:55:17. Batch auto-ack turned off in the tool. | `3FE6F23600A98AC80012007F01FE041A…` |
| 2026-10-03 | F11 | Power cut 2026-10-02 18:53 → 0202 users 5 / records 106 (seconds after start-up). Device off ~17 h, 2026-10-03 11:50 → **6 / 121** (same as before the cut). Counts read just after power-up are too low; later they return. User count never drops for deletes. | 0202 `0000000600000079` |
| 2026-10-02 | F11 | Full delete: 0502 `03000000B3` → status 1; `0300B30000` → OK; then 0502 `02FFFFFFB3` → status 1 (PIN gone, entry deleted). Users still 5. Re-add B3 (0501 OK) → **users 6**: the count only grows. | 0202 `0000000600000079` |
| 2026-10-02 | F11 | Remove member: 0502 `01000000B3` → OK; users still 5 (only the card removed). Offline QR for B3 → refused 4× (`50FF…B3`); B1 still accepted 18:42:00. | `50FF00000000000000B3261002184138` |
| 2026-10-02 | F11 | X2: account validity = now − 9000 s + 2 min (member B2) → accepted 18:17:53 and 18:19:00, **refused after the 2 min** (Naman, not logged). Short-lived offline QR confirmed. | `50EC00000000000000B2261002181900` |
| 2026-10-02 | F11 | Z1 account expired 2h15 ago → **opens**; Z2 expired 2h45 ago → **refused** (Naman). **The device runs 2.5 h behind = it reads its clock as China time (UTC+8).** | — |
| 2026-10-02 | F11 | Y: account expired 3 h ago (today) → **refused** (Naman, ~18:14, no record). So expiry is checked by time, but the device runs behind real time by 3 min–3 h (likely 2.5 h = China time). | — |
| 2026-10-02 | F11 | Account expiry as a timer: QR for B2 with account expiry = now + 2 min (≈18:10) → accepted 18:08:49, and **still accepted 18:13:03 and 18:13:22** after expiry. Expiry is enforced (yesterday = refused) but loosely: date-only or China time. Next: expiry 3 h ago today. | `50EC00000000000000B2261002181322` |
| 2026-10-02 | F11 | 0204 = 01 (time limit on) at 18:02 → V1 (window ended yesterday, B1) still accepted 18:02:29; T1 accepted 18:02:39. 0204 set back to 02. QR time window is not enforced by this firmware. | `50EC00000000000000B1261002180229` |
| 2026-10-02 | F11 | Validity test: B1 window ended yesterday → accepted 17:55:36. B2 account expired → refused (Naman), **no 0214 at all**. B3 limit 1 → first accepted 17:56:00, **second refused** (Naman), not logged. | `50EC00000000000000B1261002175536` |
| 2026-10-02 | F11 | Time-zone test: users B1–B3 added (0501; PIN 0 rejected as duplicate → unique PINs). 5-min QRs: B1 real time, B2 window ended 2.5 h ago, B3 starts in 5.5 h → **all accepted** (EC). Device ignores the QR start/duration. | `50EC00000000000000B2261002175349` |
| 2026-10-02 | F11 | Variants A–H (serial 0/FF/reversed, all doors, card type 55, lift 0001): all refused (FF). Added user card `000000A0` (0501 `000000A00000000000A0007F0000059F`, status 00, users 1→2) → QR A **accepted** twice at 17:43, door opened. Cause: QR user ID must exist in the user list. | `50EC00000000000000A0261002174326` |
| 2026-10-02 | F11 | Offline QR: raw16 key → no reaction at all. ascii32 + hex text → 0214 `50FF0000000000000001…` (QR, invalid, card 00000001) at 13:57, 16:38–16:43, 16:47; 3 beeps, no open. Duration 2880 is out of range (must be < 2880); 1440 with start 3 h ago still invalid. | `50FF0000000000000001261002164710` |
| 2026-10-02 | F14 | 0211 batch ack: 8 formats tried, none accepted. 0213 by number works (0000 = oldest, after the last → all FF). Read 75 records = 65 unique, identical to the 65 unique records received live via 0214. | 0213 `004B` → `FF…FF` |
| 2026-10-02 | F14 | Restart at ~13:12 → 0202 says **71** records (expected 58: 53 + 5 opens). 0211 at 13:12:58 → first batch of 8 records, oldest first (exit button 2026-09-13 00:11:40 …), then nothing, because the tool didn't ack (bug, fixed). | `80EC0000000000000000260913001140` |
| 2026-10-02 | F10 | Device power-cycled: last heartbeat 13:01:46, reconnected 13:02:48 (new port 41154). 0001 unanswered as the first command again; 0002/0202 fine. Heartbeat clock −8.6 s (kept through power off). First scan 13:03:00 allowed + opened. Scans before the reconnect never arrived (Naman). Old records were not re-sent. 0202 count history: 32→40 (09-30), 32 (10-02 10:04), 40…53 by 10:50, **45 at 12:41**, 53 at 13:02 after 16 more opens. It drops by 8 after each restart ❓ Every open still arrived live as 0214. | heartbeat @ 13:02:48 |
| 2026-10-02 | F5 | 16 scans in total, 2–3 s apart, many while the door was still open: all reached the server, each got 0201 + its own type-70 record. Open time 5 s → 10 s (0201 `0A`) from 12:52:00. | 0201 `0A` @ 12:52:00.621 |
| 2026-10-02 | F3 | Short token QR `GW:1:xxxxxx` (11 chars, 21×21 grid vs 45×45 for the encrypted one) scanned easily; the device forwarded it as `P` + text. Not opened yet: the allow list was empty and grant = status. | 0215 `PGW:1:FB1239` @ 10:59:07 |
| 2026-10-02 | 3.21 | Scans while the server was down (10:48:44–10:50:04 and 10:51:44–10:52:17): after each restart only the normal connect sequence came in. There was no 0215 and no 0214, and the 0202 count stayed 53 records. | 0202 `0000000100000035` @ 10:50:08 and 10:52:21 |
| 2026-10-02 | 4.11 | Duplicate 0214: record `…261002104825` sent at 10:48:30 and again at 10:48:35, although the first was acked | `70EC0000000000000000261002104825` |
| 2026-10-02 | 3.19/3.20 | Online QR: 6 bad presets scanned from the phone, each denied by the rules for the right reason (expired / start in future / wrong key → bad header + CRC / SN BB900022 / no door 1 / account expired). The scan payload is P + 152-char hex text. | 0215 `5033413135…` @ 10:37:07 |
| 2026-10-02 | 1.7 | 0001 answered `BB900021` on every connect since 10:12 | — |
| 2026-10-02 | 2.4 | Heartbeat clock vs PC: −0.6 s at 10:26 (just after the sync), −4.3 s at 10:34, −8.3 s at 12:54. Each reconnect costs ~1–2 s (jumps at 10:27, 10:29, 10:50, 10:52, 10:56); otherwise ~3–4 s/h. The earlier 0.3–0.4 s/min estimate was wrong. | heartbeat `27341005021026BB` @ PC 10:34:31.3 |
| 2026-10-02 | 2.5/2.6 | 0203 `03` OK. 0201 `05` (auto-allow) still opened 5 s. 0201 `01`/`02` sent by hand OK. 0201 `00` alone opened for 3 s (the 0203 time). Each open adds a type-70 record (count 32 → 50). | 0201 `00` @ 10:26:02 |
| 2026-09-30 | 1.8/4.11 | After connecting, the device pushed all 32 stored records as 0214 (Type 02), one per second, each waiting for our ack (FA 0214 Type 02, no data, with the ID block), which works. Records were exit-button presses and keypad PIN attempts, stamped with the wrong clock. | `AFFFFFFFFFFFFFFFFF03930010BB9000210214020080EC0000000000000000260913001140` |
| 2026-09-30 | 0.5/1.12 | Wire = ASCII hex text; 8-byte FF ID block after the head; serial BB900021; heartbeat 0101 every 1 s with BCD clock (clock wrong: 2026-09-16 02:18) | `AFFFFFFFFFFFFFFFFF029C0008BB9000210101000009180203160926BB` |
| 2026-10-18 | serial | Vendor command 0000 (`AFFFAC88` + `BB900021`, header serial FFFFFFFF) sent from the UI "Set serial" button → serial restored: 0001/0002/0202 and heartbeats use `BB900021` again. | `FAFFFFFFFFFFFFFFFF08530008FFFFFFFF00000100AFFFAC88BB900021` |
