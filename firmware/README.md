# Jar firmware — phase 1, step 1: bench capture

Hold the button, speak, release. The pendant saves a WAV on the microSD card and,
when home Wi-Fi is up, uploads it to the server on your PC. A memo is deleted
from the card only after the server confirms the same SHA-256 checksum.

```
jar/
├── firmware/   PlatformIO project for the XIAO ESP32S3 Sense
└── server/     FastAPI stub that receives and stores memos
```

## 1. Server (spare PC)

```bash
cd server
pip install -r requirements.txt
```

Linux / macOS:
```bash
JAR_DEVICE_TOKEN=YOUR-TOKEN uvicorn server:app --host 0.0.0.0 --port 8080
```

Windows PowerShell:
```powershell
$env:JAR_DEVICE_TOKEN="YOUR-TOKEN"
uvicorn server:app --host 0.0.0.0 --port 8080
```

Allow TCP port 8080 through the Windows firewall (private network only).
Memos land in `server/data/memos/<date>/<id>.wav` with a `.json` beside each.

Test it before the hardware arrives:
```bash
python fake_device.py --url http://localhost:8080 --token YOUR-TOKEN
# → 201 {"id": "...", "sha256": "...", "status": "stored"}
```

## 2. Wiring (breadboard)

| Part | Connect |
|---|---|
| Push button | D1 (GPIO2) ↔ GND. Internal pull-up, no resistor needed |
| Vibration motor driver | D3 (GPIO4) → 220 Ω → transistor input; see note below |
| Vibration motor | 3V3 → motor + ; motor − → transistor drain/collector; source/emitter → GND |
| Flyback diode 1N4148 | Across the motor, stripe (cathode) to 3V3 |
| Status LED (optional) | D4 (GPIO5) → 330 Ω → LED → GND |

The Sense board's mic (GPIO41/42) and SD card (CS GPIO21) are internal: nothing to wire.
The XIAO's own orange LED shares GPIO21 with the SD card, so it can't be used for status.

**Transistor note:** a 2N7000 is only partly switched on at 3.3 V gate drive
(its threshold can reach 3 V). Add a 100 kΩ resistor from gate to GND. If the buzz
is weak, swap to an NPN (2N2222 / S8050 / BC337) with a 1 kΩ base resistor.
You'll need a few resistors (220 Ω, 330 Ω, 1 kΩ, 100 kΩ); they weren't in the order.

## 3. Firmware

1. Install VS Code + the PlatformIO extension.
2. Copy `firmware/src/config.example.h` to `firmware/src/config.h` and fill in
   your Wi-Fi, the PC's LAN IP, and the same token as the server.
3. Format the microSD as FAT32 (32 GB max) and insert it in the Sense board.
4. Open the `firmware` folder in PlatformIO → Upload → Monitor (115200 baud).

The first build downloads the ESP32 toolchain (a few minutes).

## Feedback

| You feel | Meaning |
|---|---|
| 1 short buzz at power-up | Ready |
| 1 short buzz when pressed | Recording started |
| 2 short buzzes on release | Memo saved |
| 1 long buzz on release | Under 0.6 s, discarded |
| 3 long buzzes | Error (SD or mic); see serial monitor |

## Step-1 exit test (from the spec)

- [ ] Record 20 memos of different lengths (2 s to 2 min)
- [ ] All 20 appear on the server with matching `.json`; the card's `/memos` folder ends empty
- [ ] Turn off the router, record 5 memos, turn it back on: all 5 upload within a minute
- [ ] Pull USB power mid-recording, power up again: the partial memo is recovered and uploaded
- [ ] Press the button during an upload: recording starts and nothing is lost

## Known limits of step 1

- Plain HTTP on the LAN with a bearer token; HTTPS comes later.
- No deep sleep yet; power tuning is step 4 (wearable build).
- Clock comes from NTP. Memos recorded before the first sync get their time
  back-dated at upload (same boot) or the server's receive time.
- Server folders are by UTC date.
