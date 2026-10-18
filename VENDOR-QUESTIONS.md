# TCP-701: batch record upload (0x0211) does not continue

Device: TCP-701, serial BB900021, firmware 0004, TCP Client mode.

We send 0x0211. The device sends the first 8 records, then waits for our response. Whatever we reply, it does not send the next 8. It repeats the same first 8 every 5 seconds.

We send:
```
FAFFFFFFFFFFFFFFFF01800000BB90002102110100
```
Device sends 8 records:
```
AFFFFFFFFFFFFFFFFF119D0080BB9000210211020080EC0000000000000000260913001140...
```
We reply:
```
FAFFFFFFFFFFFFFFFF01810000BB90002102110200
```

**Question:** What exact response must we send after each 8 records so the device sends the next 8? Please send a complete example frame. Your document says "each response is 88 bytes"; what are these 88 bytes?

**Vendor answer (RESOLVED):** The reply to each batch of 8 records must have command byte **0x38**, not 0x88. The document is wrong ("88" is a typo by their technical staff). If we do not reply with 38, the reader thinks the server did not receive the data and does not send the next batch.

**Follow-up (2026-10-18, NOT working yet):** we tried "38" in every place we could think of. 12 records on the device, `0211` sent, the device sends the first 8 (128 bytes), we ack at once, and the device just repeats the same first 8 on the next `0211`. Acks tried (all with the FF×8 ID block, serial BB900021, head FA):
| Ack | Frame |
|---|---|
| command 0038, type 02 | `FAFFFFFFFFFFFFFFFF01A60000BB90002100380200` |
| command 0238, type 02 | `FAFFFFFFFFFFFFFFFF01A80000BB90002102380200` |
| command 0211, type 02, status 38 | `FAFFFFFFFFFFFFFFFF01B90000BB90002102110238` |
| command 0211, type 02, data 38 | `FAFFFFFFFFFFFFFFFF01BA0001BB9000210211020038` |
| command 0211, type 38 | `FAFFFFFFFFFFFFFFFF01B70000BB90002102113800` |

**Question:** Please send the **complete hex of one correct ack frame** (including head, ID block, checksum, length, serial, command, type, status and data) for a 0x0211 batch, and say whether the ack must be sent immediately or after a delay.

---

# TCP-701: offline QR code ignores its valid start time and duration

QR mode is offline (0x0602 = 01). Our encrypted QR codes are accepted correctly. The device also refuses a QR when the account validity has passed, and when the use limit is reached.

But the device **ignores the QR's "valid start time" and "duration"**. A QR whose 5-minute window ended yesterday still opens the door, and so does a QR whose window starts in 5 hours. Turning on the time-limited function (0x0204 = 01) did not change this.

**Question:** How do we make the device check the QR's valid start time and duration in offline mode? Is a setting or a newer firmware needed? Which time zone does the device use for these times?

---

# TCP-701: user count after deleting users

We delete a user with 0x0502 type 03 + user ID (e.g. `0300B30000`). The device answers OK, and the user is really gone. But the user count from 0x0202 does not go down. It only increases (5 users → delete one → still 5 → add one → 6).

Reading the users with 0x0505 shows the deleted user as an empty slot (all `00`), and a newly added user goes into a new slot after it.

**Question:** When a user is deleted, is its storage space ever reused for new users? Or does the 20,000-user limit count every user ever added? What is the correct data format for 0x0502 type 03 (user ID in which bytes)?

---

# TCP-701: device serial changed to FFFFFFFF after the device hung

We are testing the TCP-701 (firmware 0004, network module EBT3001) in TCP Client mode.

While we were sending the "set QR key" command (0x0601), the device stopped responding. It sent no reply and no heartbeat for about 6 minutes, and then restarted after a power cut. The QR key and the user list were also erased; we loaded them again.

**1. Device serial number changed.** The serial number in every message is now **FFFFFFFF** (before: **BB900021**). It stays FFFFFFFF after reboot and after "Restore" on the web page.
→ How can we set the serial number back to BB900021?

**2. Time in door records was wrong for a few hours.** The heartbeat clock was correct, but the time saved in door records was about 4 hours behind and hardly moving.
We **did use the set-time command (0x0103)**: we sent it 4 times (14:59, 15:06, 15:06, 15:08). Each time the device answered **OK**, and the heartbeat showed the correct time, but the door records **stayed wrong**. Only at 19:30, after a 5th 0x0103 and several restarts, the record time became correct.
→ Why did 0x0103 not fix the record time? Why did it become correct only hours later? What is the right way to fix it if it happens again?

**3.** Why can the device hang during the "set QR key" command, and how should we send it safely?

**Vendor answer (RESOLVED for points 1 and 2 — verified on the device 2026-10-18):**
- **Serial number (1):** The machine number was initialized/changed. To reset it, send this command: `FAFFFFFFFFFFFFFFFF08530008FFFFFFFF00000100AFFFAC88BB900021` (sets the machine number back to BB900021). The vendor also asked us to send the complete 0x0601 command we used, to find what caused the initialization. (Point 3 still open: they have asked for the exact 0x0601 frame.)
- **Record time 4 hours off (2):** Also caused by the changed machine number. The device was sending stored log records instead of real-time swipe records. Correcting the machine number fixes it.
- **Verified 2026-10-18:** after the command above the device answers 0001 and every heartbeat with `BB900021` again (the UI "Set serial" button, Commands tab, sends it). Points 1 and 2 are closed; point 3 (why 0601 hangs) is still open.

---

# TCP-701: how to make a doorbell / room call from the keypad

The protocol describes the doorbell / room call (0x0108): a visitor enters a room number on the keypad, the device rings and sends 0x0108 with the room number, and the server replies to open the door. The changelog for V2.0 says "Enter password or room number".

On our device (firmware 0004), everything typed on the keypad is treated as a **password**: `1234#` produces a door record type 21 (user password, invalid) with 1234, not a 0x0108 message. `#` alone, `#1234#` and `1234` without `#` also produce no 0x0108.

**Question:** What exactly do we press on the keypad to start a room call? Does room-call mode have to be switched on first (which command or setting)? Can password entry and room calls be used at the same time?
