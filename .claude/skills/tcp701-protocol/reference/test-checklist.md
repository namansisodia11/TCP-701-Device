# TCP-701 feature test checklist

Legend: 🟢 safe/read-only · 🟡 changes a setting (restore afterwards) · 🔴 destructive (confirm + backup first) · 👤 needs a person at the device.
Record for every test: frame sent, raw reply (hex), decoded result, pass/fail, notes → feed findings back into SKILL.md §10.

## 0. Setup
- [ ] PC wired Ethernet to same switch as device; set PC IP `192.168.3.x/24` (e.g. `.3`, which is also the device's default client-mode target).
- [ ] `ping 192.168.3.7`.
- [ ] Web UI `http://192.168.3.7` (pwd 123456): note firmware, MAC, mode = TCP Server, port 8887; module heartbeat/registration packets **off**. **Reboot device** after leaving web UI.
- [ ] Open TCP to `192.168.3.7:8887`; start a reader that logs every raw byte for the whole session (device may push unsolicited frames).
- [ ] Wire a test lock/LED to relay COM+NO, exit button to OPEN–GND, door contact to MC–GND.

## 1. Identity & basics 🟢
| # | Test | Cmd / data | Expect |
|---|---|---|---|
| 1.1 | Read serial | 0001 | AF, data = 4 B SN → use this SN in all later frames |
| 1.2 | Wrong SN in header | 0001 with serial `12345678` | Rejected or answered? (answers open question 5) |
| 1.3 | Type 00 vs 01 | 0002 with Type 00 and 01 | Does Type 01 still get a reply? |
| 1.4 | Firmware version | 0002 | 2 B version |
| 1.5 | Counts | 0202 | users (2 B) + records (2 B) |
| 1.6 | Bad checksum | 0002 with checksum ±1 | Ignored/no reply expected |
| 1.7 | Two frames in one TCP write | 0002+0202 concatenated | Both answered |
| 1.8 | Multiple clients | open 2 sockets, send on each | Up to 6 supported |

## 2. Feedback & clock 🟡
| # | Test | Cmd / data | Expect |
|---|---|---|---|
| 2.1 | Beep ×1/×2/×3 | 0102 `01`/`02`/`03` | 👤 hear beeps; status 0 |
| 2.2 | Beep invalid | 0102 `04` | status ≠0 or ignored |
| 2.3 | Sync clock | 0103 now (BCD, try weekday 1=Mon) | status 0; check display/log timestamps |
| 2.4 | Weekday convention | set time with various `ww`, then test weekday mask users | Determine numbering (open Q 8) |

## 3. Heartbeat & events
| # | Test | Cmd / data | Expect |
|---|---|---|---|
| 3.1 | Passive listen 5 min | — | Does device send 0101 on its own? Record interval and bytes |
| 3.2 | Set interval 10 s | 0205 `000A` 🟡 | Heartbeats every 10 s |
| 3.3 | Host-sent heartbeat | 0101 | Device reply format |
| 3.4 | Ignore 3 heartbeats | don't ack | Auto-upload stops; ack again → resumes |
| 3.5 | Door sensor | 👤 open/close door contact | 0109 `01`/`00` every 5 s until acked; ack stops it |
| 3.6 | Doorbell | 👤 enter room no. + `#` | 0108 `90`+room; reply `00` → keeps ringing? `*` silences |
| 3.7 | Doorbell remote open | reply 0108 data `01` | Relay fires |

## 4. Door control 🟡
| # | Test | Cmd / data | Expect |
|---|---|---|---|
| 4.1 | Remote unlock default | 0201 `00` | Relay for default time; log type 60 created |
| 4.2 | Remote unlock 5 s | 0201 `05` | Relay 5 s |
| 4.3 | Relay hold time 3 s | 0203 `03` | Subsequent opens hold 3 s |
| 4.4 | Toggle mode | 0203 `FF` | Relay toggles per open; **restore** to e.g. `03` |
| 4.5 | Exit button | 👤 short OPEN–GND | Relay fires; log type 80 |

## 5. Users / cards
| # | Test | Cmd / data | Expect |
|---|---|---|---|
| 5.0 | **Backup** users | 0505 (ack each packet) | Save all records to file 🟢 |
| 5.1 | Add card user | 0501 real card UID, PIN 0, ID 1, group 0, `7F`, 0000–059F | status 0; 👤 card opens door (log 10) |
| 5.2 | Card byte order | 👤 swipe unknown card in online/mixed mode → 0215 shows UID | Compare to UID printed/phone NFC reader (reverse-card option, open Q 6) |
| 5.3 | Add PIN user | 0501 card 0, PIN 123456 (`0001E240`), ID 2 | 👤 PIN + `#` opens (log 21) |
| 5.4 | Duplicate card / PIN / ID | 0501 again | status 1 / 2 / 3 |
| 5.5 | Batch add 16 | 0504 `10`+16×16 B | status 0; 0202 users +16 |
| 5.6 | Batch with duplicates | 0504 including an existing user | Data returns rejected records |
| 5.7 | Batch read | 0505 | All users, 16 per packet |
| 5.8 | Delete card only | 0502 `01`+card | Card fails, PIN still works |
| 5.9 | Delete PIN only | 0502 `02`+PIN | PIN fails |
| 5.10 | Delete by ID | 0502 `03`+`0000`+ID 🔴 | User gone (verify data layout, open Q 9) |
| 5.11 | Temporary user | 0501 group `FF`, expiry now+2 min | Works, then fails after expiry |
| 5.12 | Format users | 0503 🔴 | 0202 users = 0; restore from 5.0 via 0504 |

## 6. Access rules 🟡
| # | Test | Cmd / data | Expect |
|---|---|---|---|
| 6.1 | Open mode card-only | 0107 `01` | PIN rejected |
| 6.2 | Open mode PIN-only | 0107 `02` | Card rejected |
| 6.3 | Restore | 0107 `03` | Both work |
| 6.4 | Time-limit on | 0204 `01` + user group 1, window excluding now | Rejected |
| 6.5 | Weekday mask | user mask excluding today | Rejected; learn bit order |
| 6.6 | Time-limit off | 0204 `02` | Same user accepted |
| 6.7 | Device validity window | 0104 past, 0105 future | Normal; then 0105 in past → all rejected? then restore 🔴-ish |

## 7. Online / offline / mixed
| # | Test | Cmd / data | Expect |
|---|---|---|---|
| 7.1 | Offline | 0106 `00` | Known card opens, unknown denied, no 0215 |
| 7.2 | Mixed (default) | 0106 `02` | Known card local; unknown card → 0215 `10`+UID |
| 7.3 | Online | 0106 `01` | Every card → 0215; nothing opens without server |
| 7.4 | Grant via reply | reply 0215 Type 02 Status 00 | Door opens? (open Q 2) |
| 7.5 | Deny via reply | reply Status 01 | Denied feedback? |
| 7.6 | Grant via 0201 | send 0201 after 0215 | Door opens |
| 7.7 | No server response | disconnect host | Timeout behaviour, beep pattern |
| 7.8 | PIN in online | 👤 PIN | 0215 `21`+PIN hex |
| 7.9 | Exit button in online | 👤 | 0215 `80 00`? |

## 8. Logs
| # | Test | Cmd / data | Expect |
|---|---|---|---|
| 8.1 | Read new | 0210 | ≤8 records/batch, ack each, state EC |
| 8.2 | Read new again | 0210 | Empty (records marked uploaded) |
| 8.3 | Read all | 0211 | All records incl. uploaded — **save to file (backup)** |
| 8.4 | Single record | 0213 `0000`, `0001` | 16 B record |
| 8.5 | Real-time push | 0214, then 👤 swipe/button | Record pushed immediately; ack format |
| 8.6 | Decode types | produce card/PIN/button/remote/QR opens | Types 10/21/80/60/50 appear correctly |
| 8.7 | Offline buffer | disconnect host, generate opens, reconnect | Records uploaded after reconnect/heartbeat ack |
| 8.8 | Format logs | 0212 🔴 (after 8.3 backup) | 0202 records = 0 |

## 9. QR code
| # | Test | Cmd / data | Expect |
|---|---|---|---|
| 9.1 | Set key | 0601 32 ASCII-hex chars 🔴 (invalidates old QR) | status 0 |
| 9.2 | Offline QR mode | 0602 `01` | — |
| 9.3 | Valid QR | build payload (device SN, door 1 bit, start now, 5 min), CRC32, RC4 with key, hex text → QR | 👤 door opens, log 50 |
| 9.4 | Expired QR | start now−10 min, duration 5 | Rejected |
| 9.5 | Wrong SN / wrong door bit / bad CRC / wrong key | — | Rejected |
| 9.6 | Use limit | limit 1, scan twice | Second rejected |
| 9.7 | Online QR mode | 0602 `02` | Scan → 0215 16 B `50…` payload |
| 9.8 | Plain text QR in online mode | any text | What gets forwarded? |

## 10. Wiegand & hardware 👤
- [ ] External Wiegand-26 reader on D0/D1: card read → opens/logs type 11 / 0215.
- [ ] Relay NO/NC continuity with multimeter.
- [ ] Power range 9 V and 24 V.

## 11. Network modes 🟡 (web UI, reboot after each)
- [ ] DHCP on → find new IP, reconnect.
- [ ] TCP Client → device connects to `192.168.3.3:8888`; run harness as server; heartbeats/events arrive (production-like topology for a cloud server).
- [ ] Timeout restart / reconnect settings behave as documented.
- [ ] Restore TCP Server 192.168.3.7:8887.

## 12. OTA 🔴 — only with vendor firmware
- [ ] 0002 version only (🟢). Skip 0003/0004 unless the vendor provides firmware and recovery instructions.
