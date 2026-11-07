# TCP-701 Check-in Hardware

Testing and integration work for the **TCP-701** networked QR / IC-card access-control reader, which Gymwale plans to use for gym check-in. The device scans a member's QR code (or a card or keypad PIN), asks our server whether to let them in, and drives the door relay (a magnetic lock).

This repo holds:
- a **local test server and dashboard** that acts as the Gymwale backend
- what we learned about the device **from tests on real hardware** (the vendor manual is wrong in several places)
- an **implementation guide** for building the production server

```
  [TCP-701 reader]  --TCP (ASCII-hex frames)-->  Gymwale server :8888
   QR / card / PIN                                decides allow / deny
   door relay  <------- 0215 reply + 0201 unlock --
```

## Repository layout

| Path | What it is |
|---|---|
| [`IMPLEMENTATION-GUIDE.md`](IMPLEMENTATION-GUIDE.md) | **Start here if you're building the server.** Wire protocol as it really works, online/offline modes, users, records, time, reliability rules, reset recovery |
| [`DEVICE-NOTES.md`](DEVICE-NOTES.md) | Plain-language findings from testing, incidents, network setup, web-page buttons |
| [`TESTING-PLAN.md`](TESTING-PLAN.md) | Live feature checklist (F1–F21) with results and dates |
| [`COMMANDS.txt`](COMMANDS.txt) | Log of every protocol command: what we send, what the device answers, tested or not |
| [`tools/tcp701-tester/`](tools/tcp701-tester/) | Local test server + web dashboard + mock device ([README](tools/tcp701-tester/README.md)) |
| [`.claude/skills/tcp701-protocol/`](.claude/skills/tcp701-protocol/) | Full protocol reference: frame format, every command, QR encryption, test checklist |
| `*.doc`, `*.docx`, `*.pdf` | Original vendor manuals (protocol API, network configuration, catalog) |
| `device-*.json` | Snapshots of users and records downloaded from the test device |

## Quick start: the tester

Needs Python 3.10+ on Windows (other systems work with the usual venv paths).

```powershell
cd tools\tcp701-tester
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

- Dashboard: **http://localhost:8000**
- The device connects to this PC on **port 8888**. The tool prints this PC's IP addresses at startup.
- Allow Python through Windows Firewall on **Private** networks.

No device yet? Run the mock in a second terminal:

```powershell
.venv\Scripts\python mock_device.py --connect 127.0.0.1:8888
```

Run the tests:

```powershell
.venv\Scripts\python -m pytest tests
```

Device setup (work mode, target IP), the QR tab, the phone QR page and the other dashboard tabs are covered in the [tester README](tools/tcp701-tester/README.md).

## Device setup in short

1. Open the device's web page (factory address `http://192.168.3.7`, password `123456`).
2. Set **Work mode = TCP Client**, **Target IP = the server's IP**, **Target port = 8888**.
3. Click **Submit**, then **Reboot**. Submit alone does not apply the settings.
4. Give the server a fixed IP (reserve it in the router). If its IP changes, the device can't find it.

## Key findings

These differ from the vendor manual or are easy to get wrong. Details are in the [implementation guide](IMPLEMENTATION-GUIDE.md).

- **Frames are ASCII hex text**, not binary, and include an 8-byte `FF` ID block that the manual doesn't mention. The checksum covers Length to the end of Data.
- **Opening the door takes two messages:** the `0215` "allow" reply alone does not open it. Send `0201 unlock` right after.
- **Online QR mode (`0602 = 02`):** every scan reaches the server, including quick back-to-back scans while the door is still open. If the server is down, scans are lost.
- **Offline QR mode (`0602 = 01`):** the device decrypts the QR itself (RC4, ascii32 key, hex text). The QR's user ID must be a card number in the device's user list. The device reads its clock as China time (UTC+8), and the QR time window is not enforced, so expiry goes in the account-validity field.
- **Records (`0214`)** are reported live. Unacknowledged ones are re-sent after a reconnect, and duplicates happen, so the server must deduplicate.
- **Clock drift:** about 8 s behind in 2.5 h. The server should re-sync time (`0103`) on connect and daily.
- ⚠ **Loading the QR key (`0601`) once hung the controller.** After a power cut it came back with its serial set to `FFFFFFFF` and its users and key erased. Take the serial from the device's own messages, and wait for OK and verify after every settings write. Recovery steps are in the implementation guide, §9a.

## Test status

| | Feature |
|---|---|
| ✅ | F1 Valid QR opens (online) · F2 Bad QRs refused · F3 Short token QR · F4 Door open time · F5 Back-to-back scans |
| ✅ | F6 Exit button · F7 Remote unlock · F8 Member feedback (beeps) |
| ✅ | F9 Server down · F10 Power cut / cable out · F11 Offline QR backup · F21 Keypad PIN |
| ✅ | F13 Live entry records · F14 Download stored records |
| ⏳ | F12 Clock re-sync (server-side work) · F18 ~2,000 users batch load · F19 Long offline outage |
| ⏳ | F15 RFID card · F16 Door-left-open sensor · F17 Doorbell |

The current state is always in [`TESTING-PLAN.md`](TESTING-PLAN.md).

## Hardware

- Device: TCP-701 networked QR access-control reader (QR scanner, IC card reader, keypad, one door relay)
- Inside: an Ebyte EBT3001 network module (Ethernet, own web page) and the access controller (firmware `0004`)
- Capacity (manual): 20,000 users, 60,000 stored door records
- Inputs: exit button, door sensor, Wiegand
