# SmartGuard-Vision: gate hardware (V3 bench build, layout v2)

Drawing: `docs/hardware_assembly.png`. Firmware: `firmware/smartguard_esp32/smartguard_esp32.ino` (v1.1.0).
No soldering: breadboard, pre-cut jumper wires and component legs only.

## Parts

| Have | Part |
|---|---|
| yes | ESP32 38-pin DevKit, USB-C, CP2102 USB chip (ESP32-WROOM-32) |
| yes | 830-hole breadboard (rails split halfway), MB102 power module (HW-131), SG90 servo |
| yes | active buzzer (sealed bottom, ⊕ mark, one longer leg), pre-cut jumper wire kit |
| buy | 1 green LED and 1 red LED (5 mm) |
| buy | 2 x 220 ohm resistors (bands red-red-brown) |
| buy | 1 x 470 uF electrolytic capacitor, 10 V or higher |
| buy | 9 V 1 A DC adapter, 5.5 x 2.1 mm plug, centre positive (powers the MB102) |
| nice to have | 10 male-to-male Dupont wires (easier servo connection) |
| check | a USB-C cable that carries data (charge-only cables give no COM port) |

## Why the layout looks like this

- The 38-pin ESP32 is too wide for one breadboard with both pin rows plugged in: no free holes would be left.
  So **only one pin row (5V ... 3V3) goes into column E**, and the other row hangs off the left edge.
  That is why the **left power rail is removed** first: otherwise the hanging pins would land in it and short together.
- Every hole used is on the **right half** (columns E D C B A, row 1 at the top), whose printed numbers count from the top.
- The pre-cut jumpers are rigid and lie flat, so each one runs in a straight line and never covers a hole that is used.
- The rails are **split halfway** (gap in the red and blue lines near row 30): two short jumpers bridge them.
- The buzzer legs are short and stiff (0.3 in apart), so both legs go in column E, three holes apart.
- Rows 15 and 18 join each resistor to its LED. The ESP32 pins in those rows (G35 and SP/GPIO36) are input-only,
  so the LED voltage there is harmless. Never use GPIO35 or GPIO36 for anything else.

## Wiring list (right half; "- rail" = right blue rail, "+ rail" = right red rail)

| What | From | To |
|---|---|---|
| ESP32 pin row 5V ... 3V3 | | column E, rows 2 to 20 (5V in E2, 3V3 in E20); other row hangs free |
| ESP32 GND | A7 | - rail (short jumper) |
| Servo signal (orange) | servo plug | A6 (G13) |
| Servo + (red) | servo plug | + rail, top half |
| Servo - (brown) | servo plug | - rail, top half |
| Green LED (G26) | 220 ohm D11 to D15 | LED long leg A15, short leg bent into the - rail |
| Red LED (G33) | 220 ohm C13 to C18 | LED long leg A18, short leg bent into the - rail |
| Buzzer (G25) | 2 in. jumper B12 to B32 | buzzer long leg (+) E32, short leg (-) E35; jumper A35 to - rail |
| 470 uF capacitor | + leg in + rail, stripe leg in - rail | top half, near the servo |
| Rail bridges | + rail above the gap to + rail below; same for the - rail | |
| MB102 | bottom end, right pins in the right rail (+ on the red line) | right jumper 5V, left jumper removed |

Servo plug without soldering: push one bent end of a long jumper into each hole of the servo plug,
the other end into the breadboard. (Male-to-male Dupont wires do this more neatly.)

## Rules

1. Nothing connects to the ESP32 5V (E2) or 3V3 (E20) rows. The ESP32 is powered by USB; it shares GND only.
2. The servo is powered by the MB102, never by the ESP32 (a servo start can reset the ESP32: `reset=BROWNOUT`).
3. Remove the MB102 left jumper: its left pins hang over the edge and must not carry power.
4. Wire with the adapter unplugged and the USB cable out. Check, then power up.
5. LED long leg = +. Capacitor stripe = -. Buzzer long leg / ⊕ side = +.
6. If the ESP32 tilts because only one row is plugged in, prop the hanging side on something non-conductive (an eraser, folded paper).

## Build and test in stages

### Stage 1: flash the bare board (nothing wired, not even on the breadboard)

1. Arduino IDE 2: File > Preferences > Additional boards manager URLs:
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
2. Tools > Board > Boards Manager: install **esp32 by Espressif Systems**, version 3.x.
3. Tools > Manage Libraries: install **ESP32Servo** by Kevin Harrington.
4. Plug the ESP32 in. Device Manager > Ports should show **Silicon Labs CP210x USB to UART Bridge (COMx)**.
   No port: try another cable, or install the CP210x driver from Silicon Labs.
5. Open `firmware/smartguard_esp32/smartguard_esp32.ino`. Tools > Board: **ESP32 Dev Module**. Tools > Port: that COM port. Upload.
   If it says `Failed to connect ... Wrong boot mode`, hold the **BOOT** button while it shows `Connecting....`, release when writing starts.
6. Tools > Serial Monitor, 115200 baud, line ending **Newline**. Press **RST/EN**: you should see
   `READY SMARTGUARD fw=1.1.0 reset=...`. Type `PING`: it answers `PONG`. Type `STATUS`.
7. Close the Serial Monitor (only one program can use the port).

### Stage 2: ESP32, LEDs and buzzer (USB power only, no MB102 yet)

Remove the left rail. Plug the ESP32 row into column E, add A7 to - rail, the resistors, LEDs, buzzer jumpers, and the rail bridges.

```powershell
cd C:\Users\3rdre\SmartGuard
.\venv\Scripts\Activate.ps1
python tools\hw_test.py
```

Choose `1` (TEST): green LED, red LED, a beep. If the buzzer only clicks, it is passive after all:
set `BUZZER_PASSIVE = true` in the firmware and upload again.

### Stage 3: servo and power module

Unplug USB. Put the MB102 on the bottom end (right jumper on 5V, left jumper removed), add the capacitor and the servo wires.
Plug in the 9 V adapter, press the MB102 button (its LED lights), plug USB back in, run `python tools\hw_test.py`, choose `1`:
the gate should open and close. If the arm moves the wrong way or too far, change `SERVO_CLOSED_DEG` / `SERVO_OPEN_DEG` and upload again.

### Stage 4: with the app

Close `hw_test.py`. In a new terminal (so `SG_HARDWARE` is not still 0): `python main.py`.
The status bar should say `Gate hardware: connected`. The app finds the board by itself (`SERIAL_PORT = "AUTO"`).
To force a port: `$env:SG_SERIAL_PORT="COM5"` before `python main.py`.

## Firmware behaviour

- Pins: servo GPIO13, buzzer GPIO25, green LED GPIO26, red LED GPIO33.
- Gate closed and everything off at boot, on `SAFE`, and when the app has been silent for 10 s.
- Non-blocking (millis timers); a task watchdog resets the chip if `loop()` ever hangs, and a reset closes the gate.
- `READY ... reset=<reason>` tells you why the board last restarted (`BROWNOUT` = power problem, `TASK_WDT` = firmware hang).
- Compiled against esp32 core 3.3.12 and ESP32Servo 3.2.1: 289 KB flash (22%), 22.6 KB RAM (6%).
