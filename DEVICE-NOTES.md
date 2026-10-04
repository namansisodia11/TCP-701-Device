# TCP-701 — What We Learned (simple notes)

Testing started 2026-09-30. ✔ = confirmed on the real device · ❓ = not confirmed yet

## ⚠ Incident 2026-10-03: serial became FFFFFFFF
- 13:51:42 Load key (0601) got **no reply** (earlier key loads answered at once). 13:57 power cut. After restart the device's serial is **`FFFFFFFF`** (heartbeats and 0001), no longer `BB900021`.
- Commands carrying the old serial are **silently ignored** (0002, 0202, 0601 no reply); heartbeat acks work because the tool copies the device's serial.
- Most likely: the key and serial share one settings memory; the key write erased it, didn't finish, and the power cut left it erased (erased memory reads `FF`). The QR key is probably lost too.
- Work-around: set the tool's Header serial to `FFFFFFFF`. No documented command sets the serial → vendor question.
- **More was lost** (checked 14:06–14:07 after setting the Header serial): **all users (0)**, records (0), and the **QR key** (reloaded 14:06:17, OK). Offline QR mode survived (B2 scanned → `50FF…B2` = not on the list). **Record timestamps wrong**: scans at 14:07 were stamped 10:04:00 and 10:06:06, while the heartbeat clock was correct. One QR with card `00000000` was **accepted** (`EC`) at 14:07:13 with an empty user list ❓ (which QR?).
- **The device hung on the key command, before the power cut:** heartbeats came every minute until 13:51:33; after 0601 at 13:51:42 there were **no heartbeats for 6 minutes** (connection still open) until it came back at 13:57:28. So the 0601 write crashed/hung the controller with its settings erased; the restart (power cut) brought it up with the erased settings.
- After re-adding users (14:16, OK, users 7) B2's offline QR works again, but **record times are wrong** (scans at 14:16 stamped 10:00:30, 10:00:40; the record clock seems to restart at 10:00:00 on each boot), while the heartbeat clock is right. Online mode works (0602 = 02, 14:14).
- Reboots at 14:12 and 14:23 (web page Reboot) did **not** restore the serial (still `FFFFFFFF`). A normal reboot keeps everything else: after 14:23 the **7 re-added users were still there** (users 7, records 9) and the clock was right. So only the hung key write wiped the settings; ordinary reboots are safe.
- **Record time stays wrong after Sync time** (0103 OK at 14:59:49): scan at 14:58:54 → recorded 10:00:15; scan at 15:00:03 → **11:00:01**. The record hour = real hour − 4, minutes/seconds mostly wrong; heartbeat clock correct. A second (record) clock was broken by the crash → vendor.
- **The record clock is nearly stopped** (15:00–15:09): records at real 15:00:03, 15:05:17, 15:08:45, 15:09:00 show 11:00:01, 11:00:00, 11:00:10, 11:00:10. It moved ~10 s in 9 minutes. The main (heartbeat) clock is within 1–2 s.
- **Record time and record type recovered ✔ (2026-10-03 19:31):** after Sync time at 19:30:43 one more wrong record came (19:31:02 → 11:11:00, type 50 card 0), then from 19:31:16 the records were **correct** (19:31:14, 19:31:27, 19:31:58; 2 s upload delay) and online QR openings were logged as **type 70** again. Cause unclear (the 14:59 sync didn't help; several restarts in between). Serial still `FFFFFFFF`.
- **QR mode is kept across a restart ✔:** set to online at 15:05:31; the device reconnected at 15:08:21 (restart); scans after it still went to the server (0215 at 15:08:27…). It does not fall back to offline by default.
- **The `00000000` records explained:** since the crash, an online QR opening (0215 allow + 0201) is logged as **type `50`, card `00000000`** (before the crash: type `70` remote open). E.g. unlock 15:08:40 → record `50EC…00000000` at 15:08:45. Not a security hole.
- Neither Reboot nor Restore (web page) brings the serial back; it is stored as `FFFFFFFF` now → vendor.
- Reconnected 14:55 after fixing the network (Target IP had to be re-entered; the first Submit didn't save it). Device now connects from local port 8887.
- Recovery procedure for the real server: `IMPLEMENTATION-GUIDE.md` §9a.
- Lessons: take the serial from the device's own messages; identify devices by connection/registration packet too; after settings writes wait for OK and verify.

## The device
- An access-control reader with a **QR scanner, card reader and keypad**. It drives a **door relay** (our magnetic lock).
- Inside are **two parts**:
  - a **network module** (Ebyte EBT3001), which handles Wi-Fi/LAN and has its own web page
  - the **access controller** (firmware version `0004`), which handles scanning, users and the lock
- Its ID (serial) is **`BB900021`**. ✔
- It came with **1 user** stored: card `3FE6F236`, PIN 11111112, 08:30–17:30 (read with 0505 on 2026-10-03). ✔

## Network setup ✔
- The device IP is **192.168.1.50**. It connects **to our PC** at **192.168.1.7, port 8888** (work mode "TCP Client").
- Settings are changed at `http://192.168.1.50` (password `123456`).
- After changing settings, **click Submit AND Reboot**. Submit alone doesn't apply them.
- Don't reopen the web page during testing; it pauses the device until the next reboot.
- Leave the **serial settings** (115200 8N1) alone. They are the internal link between the two parts.
- If the PC's IP changes (it comes from the router), the device can't find the server. Reserve the IP in the router.

## Web page buttons: Reboot / Submit / Restore
| Button | What it does | Notes |
|---|---|---|
| **Reboot** | Restarts the device with its current settings | Safe ✔ (2026-10-03): users, records, key, mode and clock kept; reconnects within ~10 s |
| **Submit** | Saves changed network settings (password `123456`) | Then press Reboot, or they don't take effect |
| **Restore** | Resets the **network module's network settings** to factory values | ✔ Tested 2026-10-03 14:26: IP → `192.168.3.7`, gateway → `192.168.3.1`, target IP → `192.168.3.3` (port 8888 kept). Work mode stayed **TCP client**, DHCP disable, serial 115200 8N1, registration off. Device stopped reaching the server until reconfigured. **Doesn't touch the access controller:** after several Reboots and Restores the users (7), records (9) were intact and the serial stayed `FFFFFFFF` (14:55) |

**Factory network settings** (manual): IP `192.168.3.7` static, gateway `192.168.3.1`, mode **TCP Server**, local port 8887, target `192.168.3.3:8888`. After a Restore the device most likely stops connecting to our server.

**Web page after Restore (2026-10-03):** EBT3001, version 9013-2-17, MAC `0C-3D-5E-93-75-E0`, local port 0, web port 80, DNS 114.114.114.114, outage reconnect time 10 s, reconnection times 0, network error check time 1800 s, short connection 0, "NET connected clear cache" enable, registration mode disable (custom registration message available → possible per-device ID), network/UART keepalive 0. Only Local IP, Gateway and Target IP need changing back.

⚠ **Adding the temporary address on a DHCP Wi-Fi removed the PC's normal address** (2026-10-03): `New-NetIPAddress` switched Wi-Fi to manual, `192.168.1.7` disappeared, and after re-enabling DHCP the router gave **`192.168.1.3`**. Then the device (target `192.168.1.7`) couldn't find the server. Fix: point the device's Target IP at the new address, and **reserve the PC's address in the router**. Better: use a second network adapter / cable for the temporary address, or re-enable DHCP right after (`Set-NetIPInterface -InterfaceAlias "Wi-Fi" -Dhcp Enabled`).

### Procedure: Reboot the device (safe)
1. Open `http://<device IP>` (now `http://192.168.1.50`), password `123456`.
2. Click **Reboot**. **Close the browser tab immediately** (opening/reloading the page puts the device back into configuration mode).
   Or simply unplug the power for 5 s and plug it back in.
3. Wait ~30 s. The device reconnects to the server by itself. Check in the tool: connected, 0001 serial, 0202 counts.
Nothing is lost (users, records, key, QR mode, clock all kept).

### Procedure: change network settings (Submit)
1. Open the web page, change the fields (e.g. Target IP).
2. Click **Submit**, enter `123456`, wait for the success message.
3. **Reload the page and check the values really changed** (on 2026-10-03 one Target IP change didn't save).
4. Click **Reboot** and close the tab. Settings only take effect after the restart.

### Procedure: Restore and set the network up again
Restore only resets the **network settings** (IP `192.168.3.7`, gateway `192.168.3.1`, target `192.168.3.3:8888`). Users, records, key and serial are not touched. After it, the device no longer reaches the server.
1. Note the PC's current address (`ipconfig`, Wi-Fi), e.g. `192.168.1.3`.
2. Give the PC a temporary address on the factory network (PowerShell **as Administrator**):
   `New-NetIPAddress -InterfaceAlias "Wi-Fi" -IPAddress 192.168.3.3 -PrefixLength 24`
   ⚠ On a DHCP Wi-Fi this switches the adapter to manual and **removes the PC's normal address**.
3. Open `http://192.168.3.7` (password `123456`) and set:
   - Local IP `192.168.1.50`, subnet mask `255.255.255.0`, Gateway `192.168.1.1`, DNS `8.8.8.8`
   - Work mode **TCP client**, Target IP = **the PC's address** (step 1), Target port `8888`
   - Registration mode Disable, keepalive 0, serial parameters unchanged (115200 / 8 / NONE / 1)
4. **Submit** → wait for success → reload and check → **Reboot** → close the tab.
5. Give the PC its normal address back (PowerShell as Administrator):
   ```
   Remove-NetIPAddress -InterfaceAlias "Wi-Fi" -IPAddress 192.168.3.3 -Confirm:$false
   Set-NetIPInterface -InterfaceAlias "Wi-Fi" -Dhcp Enabled
   ipconfig /renew "Wi-Fi"
   ```
6. `ipconfig`: if the PC got a **different** address than the device's Target IP, open `http://192.168.1.50` and set Target IP to the new one (Submit → check → Reboot).
7. Check in the tool: connected, serial (0001), users (0202 / 0505), QR mode, an offline/online test scan.
**Avoid the address problem:** reserve the PC's IP in the router (DHCP reservation), so it never changes.

## How it talks (differs from the manual) ✔
- Messages are sent as **text** (hex characters), not raw bytes.
- Every message has an extra **"ID block" (`FFFFFFFFFFFFFFFF`)** that the manual doesn't mention.
- Our messages must use the **same format and the device serial**. Otherwise the device **silently ignores** them.
- So after a server restart, the first commands failed until the tool learned the format. The tool now remembers it in `state.json`.

## Heartbeat (the "I'm alive" message) ✔
- The device sends it **every 60 s**, carrying its **clock**.
- If nobody replies, it resends **every 1 s**. That was the "log every second" we saw.
- The interval can be changed (command 0205, not tried yet).
- The **clock was wrong** (2026-09-16). We set it with "Sync time".
- **The clock falls behind** ✔: about 8 s in 2.5 hours after a sync. It loses ~1–2 s each time the device reconnects, plus a few seconds per hour (measured 2026-10-02).
  Our server must **re-sync the time regularly** (e.g. on every connect and every hour). Otherwise time-limited QR codes will be judged wrongly.

## Stored history ✔
- On connecting, the device **uploaded all 32 old records**, one per second, each waiting for our "got it".
- They were exit-button presses and keypad PIN attempts (probably wrong PINs).
- Every door open creates a new record (remote unlock is recorded as type "70"). The count went from 32 to 50 during testing on 2026-10-02.

## Commands tried
| Command | Result |
|---|---|
| Get serial (0001) | ✔ `BB900021` (the early no-replies came before the tool knew the message format) |
| Firmware version (0002) | ✔ `0004` |
| Count users/records (0202) | ✔ 1 user, 32 records (answer format differs from the manual) |
| Sync time (0103) | ✔ works |
| Load QR key (0601) | ✔ works |
| QR online mode (0602 = 02) | ✔ works |
| **Unlock (0201) with seconds, e.g. 5** | ✔ **opens the magnetic lock**; open time = the seconds sent (1, 2, 5 s tested) |
| Relay hold time (0203) = 3 s | ✔ accepted; used when 0201 is sent with `00`. Doesn't override 0201's own seconds |
| Unlock with `00` sent on its own | ✔ opens for the 0203 time (3 s) |
| Unlock with `00` sent in the same instant as another message | ✖ ignored (send it 0.3 s later) |

## QR codes
- **Online mode:** the device **doesn't check QR codes**. It forwards **whatever text is in any QR** (even a website QR) to our server, and **the server decides**. ✔
- So in online mode we can put **our own data** in the QR (e.g. a member token), not just the vendor format. ✔
- **Offline mode works ✔ (2026-10-02 17:43).** See the section "Offline QR: how it works" below.
- **Our encrypted QR works:**
  - It contains the member ID, device serial, door, valid-from time, duration (5 min), account expiry and a checksum.
  - It's scrambled with a **secret key** loaded into the device.
  - The server decrypts it correctly. ✔
  - The server rejects bad QR codes with the right reason ✔ (expired, not started yet, wrong key, wrong device, wrong door, account expired; all tested 2026-10-02).
- **The key** is one secret shared by the device and our server.
  - A QR made with another key is rejected.
  - Loading a new key replaces the old one, and old QR codes stop working.
  - The web page's "Restore" button probably doesn't erase it. ❓
- **Short QR codes work great** ✔ (2026-10-02): an 11-character token like `GW:1:8F3A2C` scans easily (21×21 grid vs 45×45 for our encrypted one) and arrives at the server as plain text. Good design for Gymwale: a **short token** that the server looks up.
- **Size matters:** our long QR (152 characters) was **only read when shown large** on the phone. Short QR codes read easily. Keep QR content short. ✔
- **Keep the device clock correct**, or time-limited QR codes will look expired.

## Opening the door from the server ✔ (key discovery)
- The device asks the server "allow?" with command **0215**.
- Replying "allow" (0215 status 00) **does NOT open the door** by itself.
- The door opens only when the server **also sends Unlock (0201) with seconds**. Send it just after the reply, not in the same instant.
- The tool now does this automatically (**Policy = rules, Grant = both**):
  - a valid QR opens the door ✔
  - an invalid or random QR is refused

## Offline QR: how it works ✔ (2026-10-02)
In offline mode (0602 = `01`) the **device itself** checks the QR and opens the door. No server needed.

**Three things must be in place:**
1. **The QR key** is loaded into the device (0601). We encrypt with it used as **32 ASCII characters** ("ascii32"), and the QR holds the result as **hex text** (152 characters).
   - With the key as 16 raw bytes ("raw16") + hex text, the device ignores the QR completely (no beep). The two binary-content combinations weren't tried; not needed.
2. **The QR's user ID must be a card number in the device's user list.** The device treats the QR like a card swipe. This was the missing piece:
   - Every QR whose user ID wasn't in the list was refused: 3 beeps, door shut, record state `FF`.
   - After adding user `000000A0` (0501), the same QR opened the door.
3. **The QR fields are valid:** device serial `BB900021`, door 1, inside its time window, account not expired.

**What the device sends to the server:** for every offline scan, accepted or refused, a door record **type `50` (QR) with the member's card number**. E.g. `50EC00000000000000A0…` = QR, accepted (`EC`), member `000000A0`. Refused = state `FF`. So the server still gets attendance with the member ID (better than online mode, where the record only says "remote open").

**Beeps:** accepted = normal beep and door opens; refused = **3 beeps**.

**The user we added (0501), data `000000A0 00000000 00A0 00 7F 0000 059F`:**

| Bytes | Value | Field | Meaning |
|---|---|---|---|
| 1–4 | `000000A0` | Card number | Must equal the QR's user ID. For Gymwale: the member's ID |
| 5–8 | `00000000` | PIN | None (0 = no keypad PIN) |
| 9–10 | `00A0` | User ID / slot | The device's own unique number for this user (needed to delete it later). Any unused number |
| 11 | `00` | Time group | `00` = no time restriction |
| 12 | `7F` | Days | Bit per weekday, `7F` = all 7 days |
| 13–14 | `0000` | Daily from | Minutes after midnight: 0 = 00:00 |
| 15–16 | `059F` | Daily until | 1439 = 23:59 |

The device answered status `00` (OK), and the user count went from 1 to 2. Remove it with 0502 type 3 (user ID) when no longer needed.

**⚠ The device does NOT check the QR's time window (2026-10-02 17:53, time-limit 0204 at factory setting):** three 5-minute QR codes for members B1–B3 were all accepted. B1 was valid now; B2's window had **ended 2½ h earlier**; B3's starts **5½ h later**. So in offline mode an old QR or a screenshot keeps working.
- Test users added for this: cards `000000B1`, `000000B2`, `000000B3` (user IDs `00B1`–`00B3`, PINs `FFFFFFFF`, `FFFFFFB2`, `FFFFFFB3`, every day 00:00–23:59). PIN `00000000` can only be used once: B1–B3 with PIN 0 were refused as "duplicate PIN" (status 2).
- **Validity test (17:55):** QR window ended yesterday → **accepted** (time window not checked). **Account expired yesterday → refused** (Naman), and the device logs **no record at all** for it (unknown members do get an `FF` record). Use limit 1 → first scan accepted, **second scan refused ✔** (Naman; no record logged for it either).
- So offline the device checks: **member in user list + account expiry + use limit** (+ key/serial/door). It ignores the QR's few-minute window.
- The vendor document **does describe a QR time window** ("valid start time" + "duration, max 2880 min"; its example says "valid for 24 hours"). It doesn't mention any setting needed to enable it. The only candidate is 0204 "time-limited feature" on/off.
- **Switching on the time-limit function (0204 = 01) does NOT help** (18:02): the QR whose window ended yesterday was still accepted. 0204 set back to 02 (off) afterwards.
- **Conclusion: this firmware ignores the QR start time + duration in offline mode**, although the vendor document describes them. Ask the vendor.
- **Account expiry IS checked, to the time (not just the date) ✔**, but the device reads its clock as **China time (UTC+8)**. With the clock set to India time, it thinks "now" is **2½ hours earlier** than it really is.
  - Proof (2026-10-02 ~18:15): expiry 2 min ahead → still opened 3 min after it; expired 3 h ago → refused; expired **2h15 ago → opened**, **2h45 ago → refused**.
  - So the server must write QR times as **real time − 2½ h** (9000 s) for this device. The vendor's own example also uses UTC+8.
- **Short-lived offline QR codes WORK ✔ (2026-10-02 18:17–18:19):** put the expiry in the **account-validity field** = real time **− 2½ h + a few minutes**. A 2-minute QR opened right away and was refused after its 2 minutes (Naman).

**Offline QR summary: what the device checks**

| QR rule | Checked offline? |
|---|---|
| Key + format (ascii32 + hex text) | ✔ (wrong format = no reaction) |
| Member's card number is in the device's user list (0501) | ✔ refused, 3 beeps, logged as `FF` |
| Account validity (expiry time, to the second, in UTC+8) | ✔ refused, 3 beeps, **not logged** |
| Use limit (1–9) | ✔ refused, not logged. **Counted per QR** (a new QR for the same member works again; Naman 2026-10-02) |
| QR valid-from + duration | ✖ ignored (even with 0204 on) |
| Device SN in the QR | ✖ **ignored**: a QR made for `BB900022` opened (2026-10-03) |
| Door permission | ✖ **ignored**: a "door 2 only" QR opened door 1 (2026-10-03) |
| CRC (tampered QR) | ✔ silently ignored: no beep, no record |
| Wrong key (forged QR) | ✔ silently ignored: no beep, no record |

**⚠ Security consequence (2026-10-03 13:40, registered member B2):** the device ignores the serial and door inside the QR. So **any device with the same key accepts the QR** (if the member's card number is in its list). Use a **different QR key per device** (or per gym). Forged or tampered QR codes are safe: without the key nobody can make a QR the device accepts.

**Key per building (approach):** give all devices **in one building** the same QR key, so one member QR works at every door there. Use **different keys for different branches/gyms** (members of one branch can't open another, and a leaked key only affects one building). Each device still needs the members (or the pool) in its own user list, and records arrive per device (with its serial). ❓ The "use once" memory is most likely per device, so a single-use QR may work once at each door; short validity limits this. In online mode the key doesn't matter: the server decides per device.

**Use once (limit = 1) + short validity together:** the limit stops a QR being reused after its first scan; the short validity stops an **unused** QR (screenshot, shared, saved before the membership ended) from working later. ❓ How many used QR codes the device remembers, and whether it forgets them after a power cut, is unknown.

**What is inside an offline QR (76 bytes → encrypted → 152 hex characters)**
Example: "Use once" QR for member B2, valid 3 minutes.

| Field | Bytes | Example | Meaning | Checked offline? |
|---|---|---|---|---|
| Header / type / length | 4 | `2618` `21` `48` | Fixed values from the vendor | ✔ (decrypt check) |
| Card ID (user ID) | 4 | `000000B2` | Member. **Must be a card number in the device's user list** (0501) | ✔ |
| Device SN | 4 | `BB900021` | This device | ✔ (per document) |
| Card type | 1 | `01` | `01` = IC card (the only value the document defines) | – |
| Lift user ID | 2 | `FFF1` | Lift control only; `FFF1` = not used | – |
| Lift permission groups | 12 | `FF…FF` | Lift control only; `FF` = not used | – |
| Door permissions | 32 | `00…0001` | One bit per door; last bit = door 1 | ✔ (per document) |
| Access time / reserve | 2 | `FF FF` | Reserved | – |
| **Account validity** | 4 | `6ABF878A` | Expiry, Unix time, **written in device time (−2½ h)**. Our short-QR timer | ✔ to the second |
| **Use limit** | 1 | `01` | `00` = unlimited, `01`–`09` uses. **Counted per QR** | ✔ |
| QR valid from | 4 | `6ABF869A` | Unix time | ✖ ignored |
| QR duration | 2 | `0005` | Minutes (< 2880) | ✖ ignored |
| CRC32 | 4 | `2DDD0059` | Checksum of all fields above (start value `16E008EC`) | ✔ |

Encryption: RC4 with the 0601 key used as its **32 ASCII characters**; the QR holds the result as **uppercase hex text**.

**How "use once" can work although every QR has the same member and settings:** no two QR codes are the same. Each QR is made at a different second, so its "valid from" and validity times differ, and so do its checksum and its whole encrypted text. Example, two QR codes for B2 made 1 second apart:
- validity `6ABF97FC` / start `6ABF970C` / CRC `59FB4AB7`
- validity `6ABF97FD` / start `6ABF970D` / CRC `C2EFECE6`

The device presumably remembers something per used QR (e.g. its checksum or times). Exactly what is unknown. Two QR codes made for the same member in the **same second** would be identical, and the device would treat them as one.

**Removing a member ✔ (2026-10-02 18:40):** deleting their card number (0502 `01` + card) makes their offline QR codes fail at once (`50FF…B3`, 3 beeps). The user count doesn't drop: only the card is removed, the user entry (user ID + PIN) stays. **Deleting the whole entry works:** 0502 data `03` + **user ID first** (`0300B30000` for user ID `00B3`). `03000000B3` failed. Proof: B3's PIN was gone afterwards, and re-adding B3 succeeded.
- ⚠ **The user count (0202) never goes down**: 5 after the deletes, **6** after re-adding B3. It counts entries ever added. ❓ If deleted slots aren't reused, years of joins/leaves could reach the **20,000** limit. Possible remedy: an occasional full reset (0503 erase all users, then re-add active members 16 at a time with 0504), at night. Not tested. Ask the vendor.
- ⚠ **Counts read right after a power-up are wrong (too low)**: after a power cut on 2026-10-02 18:53 it read users 5 / records 106 (before: 6 / 121). After 17 h off, on 2026-10-03 11:50, it read **6 / 121** again. The same happened to the record count earlier (32→40, 45→53). **Don't trust 0202 shortly after the device starts.** The user count still includes deleted B3 (6, real 5).
- **No records were lost in the power cut ✔** (2026-10-03 12:23, Download all records): 121 records stored (28 exit, 4 PIN, 46 remote, 43 QR; 24 refused `FF`), and **all 111 different records the server ever received live are on the device**.

**Recipe for an offline Gymwale QR:** member's card number (also added to the device with 0501), device serial, door 1, account validity = real time − 9000 s + N minutes, use limit 1, encrypted with the key as ascii32, QR as hex text.

## When the server doesn't answer or is down ✔ (2026-10-02)
- **No answer:** after a scan the device just waits. No beep, no retry (it asks only once), no "denied".
- A **late "allow" still opens the door** (tested 73 s later), because Unlock (0201) works at any time.
  → Our server must answer quickly, and should **not** send an old "allow" late (e.g. after a slow check).
- **Server down:** scanning a QR does nothing and the door stays shut. In online mode the device can't decide on its own.
- Scans made while the server is down are **lost**. They aren't sent when the server comes back, and no record is stored on the device. ✔
- **No mixed mode for QR ✔ (2026-10-03 12:57):** card/PIN mixed mode (0106 = 02) doesn't apply to QR codes. With QR offline, an unknown member's QR was refused (3 beeps, `FF`) and **not** passed to the server; a registered member opened locally.
- **No local fallback in online mode ✔ (2026-10-03 12:50–12:52):** a device-compatible encrypted QR for a **registered** member (B2) was scanned with the Ethernet cable unplugged, and again with the server stopped. The door didn't open, nothing was stored (record count unchanged) and nothing was sent after reconnecting. Online mode needs the server for every entry.
  → If Gymwale needs entry during an outage, we need a backup: offline QR mode (not tested yet), cards/PINs stored on the device, or staff opening the door by hand.

## Scanning while the gate is open ✔ (2026-10-02)
- Scans made **while the door is still open** are still sent to the server (3 scans in 6 s, all received). So we get **every QR scan** for attendance.
- Each allowed scan sends a new unlock, which the device accepts and records. ❓ Whether this **extends** the open time or the door still closes at the first scan's time: not checked yet.

## Users stored on the device (0505, 2026-10-03)
| Slot | Card | PIN | User ID | Days / hours | Who |
|---|---|---|---|---|---|
| 1 | `3FE6F236` | 11111112 | `0012` | every day, **08:30–17:30** | the original user (factory/vendor test card?) |
| 2 | `000000A0` | 0 | `00A0` | every day, 00:00–23:59 | our test member A0 |
| 3 | `000000B1` | `FFFFFFFF` | `00B1` | every day, 00:00–23:59 | test member B1 |
| 4 | `000000B2` | `FFFFFFB2` | `00B2` | every day, 00:00–23:59 | test member B2 |
| 5 | `00000000` | – | – | – | **empty: the slot of the deleted B3** |
| 6 | `000000B3` | `FFFFFFB3` | `00B3` | every day, 00:00–23:59 | B3, added again |

- ⚠ **Deleted users leave an empty slot that is NOT reused** (at least not right away): B3 re-added went into a new slot 6. The user count (0202) counts slots, so it never goes down.
  → Over years of members joining and leaving, slots run out (20,000). Remedy: an occasional **full reset** (erase all users 0503, then re-add active members with 0504). Still to test.
- ⚠ **Reading all users (0505): never send our "got it" reply.** The device answers it by sending the same batch again at once. The tool's automatic reply caused an endless loop (101 times in 8 s) and the device reconnected. Fixed in the tool (automatic batch reply now off). With up to 16 users the first batch already has everything. Re-run after the fix (2026-10-03 11:58): one reply, same 6 slots (5 users + 1 empty), no loop ✔.
- The original user (card `3FE6F236`, PIN 11111112, 08:30–17:30) explains the PIN attempts in the first records. A PIN like 11111112 can open the door from the keypad during those hours.

**Erase all users (0503) ✔ (2026-10-03):** OK after ~20 s; user count back to **0**, so a full reset also clears the empty slots. Erase all logs (0212) took ~15 s. **Slow commands:** the reply can come long after a normal 3-second wait.

**Full user reset cycle ✔ (2026-10-03 12:31–12:36):** erase all users (0503) → offline QR for B2 **refused** → re-add 7 users in **one** batch command (0504, `07` + 7×16 bytes) → OK at once → user count **7** (no empty slot left) → B2's offline QR **accepted** again. So the "reset now and then" remedy for deleted slots works.

## Offline mode during a network outage ✔ (2026-10-03 13:20)
- Cable unplugged → B2's offline QR codes were **accepted twice** (13:20:50, 13:20:57), door opened.
- Cable back in → the device reconnected (13:21:11) and **uploaded both records on its own** (13:21:13 and 13:21:14), with card number and real scan time. Automatic log sync works. **Only the missing records were sent**: the 10 other stored records (already delivered live and acknowledged, e.g. the 13:20:33 scan) were not sent again. Nothing else arrived in the 3 minutes after.
- The server did **not** notice the cut: the dead connection just stayed open until the device reconnected. Detect "device offline" by **missing heartbeats** (one per 60 s), not by the connection closing.

## Approach: a pool of fixed user slots (idea, not tested)
Deleted users leave empty slots that aren't reused, so adding and deleting members over years could use up the 20,000 slots. One way around it:

- **Once:** load a pool of users onto the device (batch add 0504, 16 per command), e.g. card numbers `00000001`, `00000002`, … Never delete them.
- **The server keeps the mapping** pool card number ↔ member. The device only checks that the QR's card number is in its list; it doesn't need to know who the member is.
- **Member joins:** the server assigns a free slot. Nothing is sent to the device.
- **Member scans:** the server issues a QR with that slot's card number, **use once + valid for a few minutes**.
- **Member leaves / is blocked:** the server stops issuing QR codes and frees the slot once their last QR has expired. Nothing is sent to the device.
- **Attendance:** the door record ("QR, card `00000002`") is matched to whoever held that slot at that time.

**Card number vs user ID (two different IDs per device user):**

| Field | Size | Used for |
|---|---|---|
| **Card number** | 4 bytes | What the **QR** carries and what the **door record** shows. The device matches QR ↔ user list on this. (The vendor document calls the QR field "user ID", but it is matched against the card number.) |
| **User ID** | 2 bytes | The device's internal handle, only used to **delete** the entry (0502 type 03). Never in the QR or in records. |

In the pool, each slot uses the **same value for both (1:1)**, and the server maps slot → member:

| Slot | Card number | User ID | Server |
|---|---|---|---|
| 1 | `00000001` | `0001` | member A |
| 2 | `00000002` | `0002` | member B |
| 3 | `00000003` | `0003` | free |

Issuing a QR: member A holds slot 1 → the QR carries card number `00000001`. Door record "QR, card `00000001`, 18:02" → the server looks up who held slot 1 at 18:02.

Points to keep in mind:
- A blocked member can still use a QR issued in the last few minutes (keep validity short).
- Every slot needs a **unique PIN** (duplicates are refused), and PINs may work on the keypad: use long values nobody can type (e.g. `FFFFFFB1`). ❓ Check whether the keypad accepts 10-digit PINs.
- The pool size limits the number of **active members at once**, not members ever.
- Remove the original user (card `3FE6F236`, PIN 11111112) before going live.

## Power cut ✔ (2026-10-02)
- After power comes back the device **reconnects to the server by itself** and works normally. No settings were lost (online QR mode kept).
- The **clock survives** a power cut (it has a battery-backed clock).
- Scans made **before it has reconnected are lost** (pure online mode), same as when the server is down.

## Stored history on the device (0211)
- The device returns its stored records **oldest first, 8 at a time**, and waits for our "got it" before each next batch ✔.
- The oldest records go back to 2026-09-13 (exit-button presses, wrong clock at the time).
- With "read all" (0211) only the first 8 come back. The device never accepts our "got it" reply (8 formats tried).
- **Fix ✔: read records one at a time (0213)**, by number from 0 (oldest). After the last one the device returns an empty (all-FF) record.
  The tool has a **"Download all records"** button (Commands tab) that does this and saves `logs/records-*.json`.
- Result (2026-10-02): the device stores **75 records** (28 exit button, 4 PIN, 43 remote/QR opens). **Every record the server received live is also stored on the device: nothing was lost.**

## Keypad PIN entry ✔ (2026-10-03 20:00)
- Add a user with a PIN (0501). The PIN is the typed number stored as hex: **654321 → `0009FBF1`**. Test user D1: `000000D10009FBF100D1007F0000059F`.
- Typing the right PIN on the keypad **opens the gate**; a wrong PIN is refused. The device checks it **itself** (no question to the server), even with QR in online mode.
- Every try is sent to the server live as a **type 21** record: `21EC` accepted / `21FF` refused, followed by the **typed PIN** (not the member's card number). So the server must map PIN → member. Wrong PINs are reported in plain text too.
- **Works with the server off ✔**: the PIN still opens; the record is uploaded when the server is back (20:03:55 → sent 20:04:11).
- **Changing a PIN:** there's no edit command. Delete the whole user (0502 `03` + user ID + `0000`), then add it again (0501). After the delete, the old PIN is refused at once ✔ (`21FF`, 20:08).
- **Gymwale use (Naman, 2026-10-03):** PINs only for a few people, not all members, so a small PIN → person list on the server is enough.

## RFID cards (not tested yet, no card on hand)
**Which cards to buy:** the reader is **13.56 MHz IC/NFC (ISO 14443A)**. Cards from any vendor work; they don't have to come from this company.

| Card | Works? | Notes |
|---|---|---|
| **MIFARE Classic 1K (also sold as "S50" or "Fudan F08")**, 13.56 MHz | ✅ **Buy this** | 4-byte card number, matching the device's 4-byte card field. Cards, key fobs and wristbands all work. |
| NTAG213 / NTAG215 / Ultralight (NFC stickers, tags) | ⚠ Maybe | 7-byte numbers; the device may cut them to 4 bytes. Avoid. |
| 125 kHz cards (EM4100, TK4100, "proximity" or "ID" cards) | ❌ No | Wrong frequency. Check the listing says 13.56 MHz. |
| Phone NFC / bank cards | ❌ Don't rely on them | Many show a random number on each tap. |

**No card programming needed.** The device reads only the card's factory number (UID). It doesn't write to the card or read data stored on it. Setup is just: tap the card → read its number from the log → add a user with that number (0501) → it works.
- Avoid "UID changeable" or "magic" cards. They work, but anyone can set them to any number. Plain cards are cheaper and fine.
- The device checks only the number, so a cloned card would get in too. That's acceptable for a few staff cards and normal for gym or office access.
- The number printed on a card may differ from what the device reads (written in decimal, or bytes reversed). Always use the number from the log.

**Test plan for when a card arrives:**
1. Tap the unknown card with the server connected. The device reports a refused card entry with the card number (type 10 record or 0215 `10` + UID).
2. Add a user (0501): that card number, a PIN nobody can type (e.g. `FFFFFFD2`, PINs must be unique), unlimited time `00 7F 0000 059F`.
3. Tap again: the gate should open, with a type 10 record carrying the card number.
4. Quick checks: unknown card refused, deleted card (0502 `01` + card) stops working, card works with the server off.

## Doorbell / room call (0108) ✖ not working yet (2026-10-03)
- The idea: a visitor types a room number on the keypad, the device rings and sends **0108** to the server, and the server replies `01` (open) or `00` (don't open). Possible gym use: "call reception" at the gate.
- On our device the keypad treats digits + `#` as a **PIN** (`1234#` → type 21 record, PIN 1234, refused). `#` alone, `#1234#` and `1234` + wait also gave **no 0108**. The manual only says "press the door number or # key". The V2.0 changelog says the keypad takes "password **or** room number", so it's probably a mode setting we can't reach. Asked the vendor.
- 0108 is sent **device → server** only. Sending it from the dashboard does nothing (the device just beeps).
- Not needed for the gym: staff can open the gate remotely (0201).

## Beeps the member hears (2026-10-03 20:44, Naman)
| Mode | Valid QR | Invalid QR |
|---|---|---|
| Offline | 1 beep + gate opens | **3 beeps** |
| Online | 1 beep + gate opens | **1 beep** (same as valid, gate stays shut) |

In online mode a refused member hears the same beep as an accepted one. The server can send **0102 (beep ×1/2/3)** after the deny to make it clear. The tester has a "Beeps on deny" option (Access tab) for this. **Tried 2026-10-03 ~20:55:** sometimes the 3 beeps play, sometimes not. Not important (Naman), left as is.

## Other observations
- **Member feedback** ✔ (Naman): the device just passes the QR to the server. Valid scan = **2 beeps** + gate opens; denied = gate stays shut. The member gets no other message, so any "why denied" has to come from the Gymwale app.
- The record count (0202) jumped around after restarts (40 → 32, 53 → 45, 71), but the full download showed all records are there (75 = the count at 13:30). Nothing was lost.
- The device sometimes sends the **same door record twice** (seen 2026-10-02, 5 s apart, even after our "got it"). Our server must ignore duplicates.
- The connection stayed stable for hours. After a server restart the device reconnects within about 1–10 s ✔ (sometimes it opens two connections; the tool keeps the newest).
- Very long QR data could hit device limits (a 1024-byte buffer). Keep QR content under about 50 characters.

## Still to test
- Card entry (IC card); card verification mode 0106 (online/offline/mixed); keypad PIN length (6 digits works)
- Heartbeat interval (0205), door sensor (0109), doorbell (0108), beep (0102), relay toggle mode (0203 `FF`)
- Device validity dates (0104/0105)
- Whether a second unlock extends the open time
- How many used QR codes the device remembers (use limit), and after a power cut
- What happens at 60,000 records / 20,000 users

Summary for building the real server: **`IMPLEMENTATION-GUIDE.md`**.
Details: `COMMANDS.txt` (per command) · `TESTING-PLAN.md` (checklist) · `tools/tcp701-tester/` (test tool)
