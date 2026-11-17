# SmartGuard-Vision: gate hardware (V3 bench build)

Drawing: `docs/hardware_assembly.png`. Firmware: `firmware/smartguard_esp32/smartguard_esp32.ino` (v1.1.0).

## Parts

| Have | Part |
|---|---|
| yes | ESP32 38-pin DevKit, USB-C (ESP32-WROOM-32) |
| yes | 830-hole breadboard, MB102 power module (HW-131), SG90 servo, buzzer, jumper wire kit |
| buy | 1 green LED and 1 red LED (5 mm) |
| buy | 2 x 220 ohm resistors (bands red-red-brown) |
| buy | 1 x 470 uF electrolytic capacitor, 10 V or higher (steadies the 5 V rail when the servo starts) |
| buy | 9 V 1 A DC adapter, 5.5 x 2.1 mm plug, centre positive (powers the MB102) |
| check | a USB-C cable that carries data (charge-only cables give no COM port) |

## Pin map

| ESP32 pin | Breadboard hole | Goes to |
|---|---|---|
| G13 | A7 | servo signal (orange wire) |
| GND | A8 | right - rail |
| G27 | A11 | jumper to A40, 220 ohm D40-G40, red LED (long leg J40, short leg in left - rail) |
| G26 | A12 | jumper to A32, 220 ohm D32-G32, green LED (long leg J32, short leg in left - rail) |
| G25 | A13 | jumper to A25, buzzer + in E25, buzzer - in F25, jumper J25 to left - rail |
| - | rails | servo red to right + rail, servo brown to right - rail, 470 uF across the right rails (stripe on -), jumper between left - and right - rails |

The ESP32 straddles the centre gap with its G13...G25 pin row in column B and its other pin row in column J.
Column A is the only free hole next to each pin, so every ESP32 wire starts there.
Row numbers count from the top end on both halves (the left half of this board is printed upside-down).

## Rules

1. The ESP32 is powered by USB only. Never connect a + rail to its 5V or 3V3 pin. It shares GND only.
2. The servo is powered by the MB102 5 V rail, never by the ESP32 (a servo start can reset the ESP32: `reset=BROWNOUT`).
3. Before plugging in the MB102, turn it so the + printed next to its pins sits on the red line. Set the right-side jumper to 5V.
4. If a rail's red or blue line has a gap in the middle, the rail is split: bridge the two halves with a short jumper.
5. Wire with the adapter unplugged and the USB cable out. Check, then power up.
6. Use the DC jack on the MB102 as its input. Its regulator gets warm when the servo moves; that is normal for short moves.

## Build and test in stages

### Stage 1: flash the bare board (nothing wired)

1. Arduino IDE 2: File > Preferences > Additional boards manager URLs:
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
2. Tools > Board > Boards Manager: install **esp32 by Espressif Systems**, version 3.x.
3. Tools > Manage Libraries: install **ESP32Servo** by Kevin Harrington.
4. Plug the ESP32 in. Windows Device Manager > Ports should show a COM port (for example "Silicon Labs CP210x" or "USB-SERIAL CH340").
   No port: try another cable, or install the CP210x driver (Silicon Labs) or the CH340 driver (WCH).
5. Open `firmware/smartguard_esp32/smartguard_esp32.ino`. Tools > Board: **ESP32 Dev Module**. Tools > Port: that COM port. Upload.
   If it says `Failed to connect ... Wrong boot mode`, hold the **BOOT** button while it shows `Connecting....`, release when writing starts.
6. Tools > Serial Monitor, 115200 baud, line ending **Newline**. Press **EN** on the board: you should see
   `READY SMARTGUARD fw=1.1.0 reset=...`. Type `PING`: it answers `PONG`. Type `STATUS`.
7. Close the Serial Monitor (only one program can use the port).

### Stage 2: LEDs and buzzer (USB power only)

Wire the LEDs, resistors, buzzer, the A8 GND wire and the GND bridge. Then:

```powershell
cd C:\Users\3rdre\SmartGuard
.\venv\Scripts\Activate.ps1
python tools\hw_test.py
```

Choose `1` (TEST): green LED, red LED, a beep. If the buzzer only clicks, it is a passive buzzer:
set `BUZZER_PASSIVE = true` in the firmware and upload again.

### Stage 3: servo and power module

Unplug USB. Put the MB102 on the bottom end (right jumper on 5V), add the 470 uF capacitor and the servo wires.
Plug in the 9 V adapter, press the MB102 button (its LED lights), plug USB back in, run `python tools\hw_test.py` and choose `1` again:
the gate should open and close. If the arm moves the wrong way or too far, change `SERVO_CLOSED_DEG` / `SERVO_OPEN_DEG` and upload again.

### Stage 4: with the app

Close `hw_test.py`. In a new terminal (so `SG_HARDWARE` is not still set to 0):

```powershell
python main.py
```

The status bar should say `Gate hardware: connected`. The app finds the board by itself (`SERIAL_PORT = "AUTO"` in `core/config.py`).
To force a port: `$env:SG_SERIAL_PORT="COM5"` before `python main.py`.
Unplug the USB cable while the app runs: the firmware closes the gate within 10 s, and the app reconnects when you plug it back.

## Firmware behaviour

- Gate closed and everything off at boot, on `SAFE`, and when the app has been silent for 10 s.
- Non-blocking (millis timers); a task watchdog resets the chip if `loop()` ever hangs, and a reset closes the gate.
- `READY ... reset=<reason>` tells you why the board last restarted (`BROWNOUT` = power problem, `TASK_WDT` = firmware hang).
- Compiled against esp32 core 3.3.12 and ESP32Servo 3.2.1: 289 KB flash (22%), 22.6 KB RAM (6%).
