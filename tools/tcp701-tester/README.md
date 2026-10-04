# TCP-701 Tester (local server + dashboard)

This tool plays the part of **your backend server** for the TCP-701. The device runs in **TCP Client** mode and connects to this PC. Each card, PIN or QR scan arrives as a verification request (`0215`). The dashboard:
- decodes the request
- decides allow or deny (by hand or by rules)
- sends the answer back

You see **every frame in and out** live. The dashboard also generates encrypted QR codes for the device to scan. It all runs locally, with no deployment.

The test steps are in [`../../TESTING-PLAN.md`](../../TESTING-PLAN.md). The protocol reference is in `.claude/skills/tcp701-protocol/`.

```
  [TCP-701]  --TCP-->  this PC : 8888   (tool = your server)
  Work mode: TCP Client        dashboard: http://localhost:8000
  Target IP: <this PC's IP>
  Target port: 8888
```

## 1. Start the tool

```powershell
cd "tools\tcp701-tester"
python -m venv .venv                                  # first time only
.venv\Scripts\python -m pip install -r requirements.txt  # first time only
.venv\Scripts\python app.py
```
The tool starts listening on **port 8888** straight away and prints this PC's IP addresses. Use one of those as the device's Target IP. Open **http://localhost:8000**. The top bar shows the IPs too, as "device Target IP → …".

Options:
- `--listen 9000` uses a different device port.
- `--listen 0` doesn't listen at startup (use this when you connect to a device in TCP Server mode instead).
- `--port 8080` changes the dashboard port.

**Windows Firewall:** the first run asks whether to allow Python. Allow it on **Private** networks. Otherwise the device can't connect in on 8888, or a phone can't reach 8000. If you missed the prompt, run this once as Administrator:
```powershell
New-NetFirewallRule -DisplayName "TCP-701 tester" -Direction Inbound -Protocol TCP -LocalPort 8888,8000 -Action Allow -Profile Private
```

## 2. Configure the device (once)

1. Put the PC and the device on the same network. Use a switch or router, or connect directly with the PC set to a static IP.
2. Open the device's web page. The factory address is `http://192.168.3.7`. To reach it, the PC temporarily needs a `192.168.3.x` address such as `192.168.3.3/24`. The password is `123456`.
3. Set:

   | Setting | Value |
   |---|---|
   | Device IP / mask / gateway | an address on the same network as the PC (or DHCP) |
   | **Work mode** | **TCP Client** |
   | **Target IP** | **this PC's IP** (shown by the tool) |
   | **Target port** | **8888** |
   | Heartbeat packet / registration packet (module) | **off** |

4. Click **Submit**, then **power-cycle the device**.
5. The dashboard LED turns green with "device connected from …". The tool then reads the serial number, version and counts automatically.

The factory Target is `192.168.3.3:8888`. If you give the PC the static IP `192.168.3.3/24` and set only Work mode = TCP Client, no other device change is needed.

## 3. Testing QR codes and access control

**Access tab** (your server's decisions)
1. **Device verification mode**:
   - `0106` card/PIN: `01` online makes every scan come to the server; `02` mixed checks locally first, then the server.
   - `0602` QR: `02` online sends QR scans to the server; `01` offline makes the device decrypt and check locally.
2. **Policy**:
   - *manual*: each scan appears under **Pending requests** with its decoded data, and you click **Allow** or **Deny**.
   - *rules*: cards and PINs are checked against the allow list. QR codes are checked for encryption, CRC, device SN, door, time window and account validity.
   - *allow everything* / *deny everything*.
3. **How to grant**: use **both**. Tested: `0215 status 00` alone does not open the door; the `0201 unlock` sent 0.3 s later does, for the number of seconds it carries (see `DEVICE-NOTES.md`).

**QR tab**
1. **Key**: click *Random*, then *Load to device (0601)*. The tool keeps the key, so it can also decrypt QR data the device forwards.
2. Go to **Door → Sync time**. QR validity depends on the device clock.
3. Click a preset: **Valid**, then Expired, Future start, Wrong SN, Bad CRC, Wrong key, Door 2 only, Limit 1, Account expired.
4. Show the QR and scan it at the device. Click the QR (or **Fullscreen**) to show it at about 2.5 cm; the −/+ buttons change the size. You can also show the QR on a phone at full brightness, using the **phone page** below.

**Phone page** (QR screen built for mobile, phone on the same Wi-Fi):
**http://192.168.1.3:8000/static/phone.html**
This uses the PC's Wi-Fi IP. If the IP changes, `app.py` prints the current phone link at startup.
**Offline QR** on the phone page: pick a member that is on the device (added with 0501), then **Valid for N minutes**, **Expired** or **Use once**. The expiry goes in the account-validity field, shifted −2½ h because the device reads its clock as China time (see `DEVICE-NOTES.md`).
**Short token QR** on the phone page makes a plain QR from any text (or a random short token such as `GW:1:8F3A2C`). With Policy = *rules*, a text that exactly matches a line in the **Allow list** opens the door. Use this to test short-token QR codes.
5. Press **✔ Opened**, **✖ Denied** or **∅ No reaction**. The result, with all QR parameters, goes into the session log.
6. If the *Valid* QR doesn't work, switch the **RC4 key format** (raw16 ↔ ascii32) or the **QR content** format (hex text ↔ binary), then regenerate. Record which combination works (test 3.7).

To test QR codes the vendor's app made, paste the text under *Decode a QR* to see its fields and validity.

## 4. Other tabs
| Tab | Use |
|---|---|
| **Door** | Unlock (0201); beep; **sync time**; relay hold time; heartbeat interval; open mode; time-limit; auto-acknowledge toggles; doorbell auto-reply |
| **Commands** | Identify buttons, plus any command with hex data (waits for the reply) |
| **Raw** | Send any hex (checksum fixed automatically), or build a frame from fields; includes deliberately bad checksums |
| **Notes** | Adds a timestamped observation to the session log |

The **traffic table** shows `→ out` (orange) and `← in` (green). ⚖ rows are access decisions and ✎ rows are notes. Click a row for the field-by-field hex. Use **Export log** to download the session. Every session is also saved in `logs/session-*.jsonl`.

## 5. Try everything without the device
```powershell
.venv\Scripts\python app.py                              # terminal 1
.venv\Scripts\python mock_device.py --connect 127.0.0.1:8888   # terminal 2: fake device in TCP Client mode
```
The mock connects like the real device would. It sends heartbeats, door events, and card, PIN and QR verification requests. The QR requests come in both the 16-byte form and as raw encrypted text using the key you loaded with 0601. Its console shows what it received from the server, for example "server says ALLOW -> door opens".

## Tests
```powershell
.venv\Scripts\python -m pytest tests
```
The tests cover all golden frames from the spec, the spec's QR CRC example (`802916C8`), RC4/QR round trips, and the QR validation rules.

## Files
| File | Role |
|---|---|
| `protocol.py` | Frames, stream reassembly, decoders, QR payload + CRC32 + RC4 + validation |
| `device.py` | TCP server/client link, request/response matching, auto-acks, **access engine** (0215), JSONL log |
| `app.py` | FastAPI REST + WebSocket; QR generation (segno) |
| `mock_device.py` | Fake TCP-701 (TCP Client or Server mode) |
| `static/` | Dashboard UI |
