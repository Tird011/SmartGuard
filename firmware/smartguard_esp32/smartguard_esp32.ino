/*
 * SmartGuard-Vision ESP32 firmware  v1.1.0
 *
 * Board : 38-pin ESP32 DevKit with USB-C (ESP32-WROOM-32).
 *         Arduino IDE: board "ESP32 Dev Module", esp32 core by Espressif 3.x.
 * Library: "ESP32Servo" by Kevin Harrington (Arduino Library Manager).
 *
 * Controls the checkpoint gate servo, green/red status LEDs and the warning buzzer.
 * Talks to the desktop app over USB serial (115200 baud, one ASCII command per line).
 *
 * Commands (case-insensitive)      Reply
 *   PING                           PONG
 *   PASS        green LED + open gate; gate and LED auto-reset after GATE_OPEN_MS
 *   WARN        red LED + warning beeps; auto-reset after WARN_MS
 *   GATE_OPEN   open gate (auto-closes after GATE_OPEN_MS)
 *   GATE_CLOSE  close gate now
 *   BUZZ        one short beep
 *   LED_GREEN / LED_RED / LED_OFF
 *   SAFE        gate closed, LEDs off, buzzer off
 *   TEST        bench self-test: green, red, beep, gate open, gate close (about 5 s)
 *   STATUS      STATUS gate=<open|closed> green=<0|1> red=<0|1> buzzer=<0|1> host=<0|1> up=<seconds>
 *   every accepted command -> "OK <CMD>", unknown -> "ERR UNKNOWN", too long -> "ERR TOO_LONG"
 * Unsolicited lines:
 *   READY SMARTGUARD fw=<version> reset=<reason>    once at boot
 *   EVT HOST_LOST                                   the desktop app went silent, outputs made safe
 *
 * Safety design
 *   - Gate closed and everything off on boot, on SAFE, and when the host goes silent for
 *     HEARTBEAT_TIMEOUT_MS (app crash, cable pulled). The app sends PING every 2 s.
 *   - Nothing blocks: every timer uses millis(), so serial is always answered.
 *   - Task watchdog on loop(): if the firmware ever hangs, the ESP32 resets within 5 s,
 *     and a reset closes the gate. The READY line then reports reset=TASK_WDT.
 *
 * Wiring: every signal uses ONE header row of the board (the row with 3V3 ... 5V),
 * so the board fits a single breadboard. See docs/hardware_assembly.png.
 *   GPIO13 -> servo signal (orange)        servo power from the MB102 5 V rail, NOT the ESP32
 *   GPIO25 -> buzzer +                     (buzzer - to GND)
 *   GPIO26 -> 220 ohm -> green LED anode   (cathode to GND)
 *   GPIO27 -> 220 ohm -> red LED anode     (cathode to GND)
 *   GND    -> breadboard GND rail (shared with the MB102 and the servo)
 * GPIO 0, 2, 5, 12, 15 are boot-strapping pins and GPIO14 pulses at boot: none are used.
 */
#include <Arduino.h>
#include <ESP32Servo.h>
#include <esp_system.h>

#if !defined(ESP_ARDUINO_VERSION_MAJOR) || ESP_ARDUINO_VERSION_MAJOR < 3
#error "Install the esp32 board package by Espressif, version 3.x (Tools > Board > Boards Manager)."
#endif

#define FW_VERSION "1.1.0"

// ---------------- EDIT THESE TO MATCH YOUR WIRING ----------------
constexpr uint8_t PIN_SERVO     = 13;
constexpr uint8_t PIN_BUZZER    = 25;
constexpr uint8_t PIN_LED_GREEN = 26;
constexpr uint8_t PIN_LED_RED   = 27;
constexpr uint8_t PIN_STATUS    = 2;     // on-board LED on most DevKits: lit while the app is connected

// Active buzzer (beeps on its own when powered) = false. Passive buzzer (only clicks) = true.
constexpr bool     BUZZER_PASSIVE  = false;
constexpr uint32_t PASSIVE_TONE_HZ = 2700;

constexpr int SERVO_CLOSED_DEG = 0;
constexpr int SERVO_OPEN_DEG   = 90;
constexpr int SERVO_MIN_US     = 500;    // SG90 pulse range
constexpr int SERVO_MAX_US     = 2400;

constexpr uint32_t GATE_OPEN_MS         = 5000;   // how long the gate stays open
constexpr uint32_t WARN_MS              = 3000;   // how long the warning lasts
constexpr uint32_t BEEP_ON_MS           = 150;
constexpr uint32_t BEEP_OFF_MS          = 100;
constexpr uint32_t HEARTBEAT_TIMEOUT_MS = 10000;  // host silent this long -> SAFE
constexpr uint32_t BAUD                 = 115200;
// -----------------------------------------------------------------

Servo gate;
ESP32PWM buzzerPwm;                       // passive buzzer only; shares the servo library's channel allocator

bool gateOpen = false, gateTimer = false;      uint32_t gateCloseAt = 0;
bool greenOn = false, redOn = false;
bool ledTimer = false;                         uint32_t ledOffAt = 0;
bool beeping = false, buzzerOn = false;        uint32_t beepEndAt = 0, beepToggleAt = 0;
bool hostSeen = false;                         uint32_t lastHostMs = 0;
uint8_t testStep = 0;                          uint32_t testNextAt = 0;   // 0 = no self-test running

char buf[24];
uint8_t len = 0;
bool overflow = false;

// Wrap-safe "has time t arrived?" (millis() overflows after ~49 days).
bool due(uint32_t t) { return (int32_t)(millis() - t) >= 0; }

void setBuzzer(bool on) {
  buzzerOn = on;
  if (BUZZER_PASSIVE) {
    if (on) buzzerPwm.writeTone(PASSIVE_TONE_HZ);
    else    buzzerPwm.write(0);
  } else {
    digitalWrite(PIN_BUZZER, on ? HIGH : LOW);
  }
}

void setLeds(bool g, bool r) {
  greenOn = g; redOn = r;
  digitalWrite(PIN_LED_GREEN, g ? HIGH : LOW);
  digitalWrite(PIN_LED_RED, r ? HIGH : LOW);
}

void setGate(bool open) {
  gate.write(open ? SERVO_OPEN_DEG : SERVO_CLOSED_DEG);
  gateOpen = open;
  gateTimer = open;
  if (open) gateCloseAt = millis() + GATE_OPEN_MS;
}

void startBeeps(uint32_t durationMs) {
  beeping = true;
  beepEndAt = millis() + durationMs;
  setBuzzer(true);
  beepToggleAt = millis() + BEEP_ON_MS;
}

void stopBeeps() { beeping = false; setBuzzer(false); }

void safeState() {
  testStep = 0;
  setGate(false);
  setLeds(false, false);
  stopBeeps();
  ledTimer = false;
}

const char *resetReason() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:  return "POWERON";
    case ESP_RST_SW:       return "SOFTWARE";
    case ESP_RST_PANIC:    return "PANIC";
    case ESP_RST_INT_WDT:  return "INT_WDT";
    case ESP_RST_TASK_WDT: return "TASK_WDT";
    case ESP_RST_WDT:      return "WDT";
    case ESP_RST_BROWNOUT: return "BROWNOUT";   // usually: servo powered from the ESP32
    case ESP_RST_EXT:      return "EXTERNAL";
    default:               return "OTHER";
  }
}

// Self-test, one step at a time so serial stays responsive.
void runTest() {
  if (testStep == 0 || !due(testNextAt)) return;
  uint32_t wait = 1000;
  switch (testStep) {
    case 1: setLeds(true, false);  break;                       // green
    case 2: setLeds(false, true);  break;                       // red
    case 3: setLeds(false, false); startBeeps(BEEP_ON_MS); wait = 500; break;
    case 4: setGate(true);         wait = 1500; break;          // open
    case 5: setGate(false);        break;                       // close
    default: testStep = 0; Serial.println("EVT TEST_DONE"); return;
  }
  testStep++;
  testNextAt = millis() + wait;
}

void handleCommand(const char *cmd) {
  if (strcmp(cmd, "PING") == 0) { Serial.println("PONG"); return; }

  if (strcmp(cmd, "PASS") == 0) {
    testStep = 0;
    setLeds(true, false);
    stopBeeps();
    setGate(true);
    ledTimer = true; ledOffAt = gateCloseAt;
  } else if (strcmp(cmd, "WARN") == 0) {
    testStep = 0;
    setGate(false);
    setLeds(false, true);
    startBeeps(WARN_MS);
    ledTimer = true; ledOffAt = millis() + WARN_MS;
  } else if (strcmp(cmd, "GATE_OPEN") == 0) {
    setGate(true);
  } else if (strcmp(cmd, "GATE_CLOSE") == 0) {
    setGate(false);
  } else if (strcmp(cmd, "BUZZ") == 0) {
    startBeeps(BEEP_ON_MS);                 // one beep
  } else if (strcmp(cmd, "LED_GREEN") == 0) {
    setLeds(true, false); ledTimer = false;
  } else if (strcmp(cmd, "LED_RED") == 0) {
    setLeds(false, true); ledTimer = false;
  } else if (strcmp(cmd, "LED_OFF") == 0) {
    setLeds(false, false); ledTimer = false;
  } else if (strcmp(cmd, "SAFE") == 0) {
    safeState();
  } else if (strcmp(cmd, "TEST") == 0) {
    safeState();
    testStep = 1; testNextAt = millis();
  } else if (strcmp(cmd, "STATUS") == 0) {
    Serial.printf("STATUS gate=%s green=%d red=%d buzzer=%d host=%d up=%lu\n",
                  gateOpen ? "open" : "closed", greenOn, redOn, buzzerOn, hostSeen,
                  (unsigned long)(millis() / 1000));
    return;
  } else {
    Serial.println("ERR UNKNOWN");
    return;
  }
  Serial.print("OK ");
  Serial.println(cmd);
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (overflow) { Serial.println("ERR TOO_LONG"); overflow = false; }
      else if (len > 0) {
        buf[len] = 0;
        lastHostMs = millis();                       // any complete line counts as a heartbeat
        if (!hostSeen) { hostSeen = true; digitalWrite(PIN_STATUS, HIGH); }
        handleCommand(buf);
      }
      len = 0;
    } else if (len < sizeof(buf) - 1) {
      buf[len++] = toupper((unsigned char)c);
    } else {
      overflow = true;                               // discard the rest of this line
    }
  }
}

void setup() {
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_STATUS, OUTPUT);
  digitalWrite(PIN_STATUS, LOW);
  if (BUZZER_PASSIVE) {
    buzzerPwm.attachPin(PIN_BUZZER, PASSIVE_TONE_HZ, 10);
    buzzerPwm.write(0);
  } else {
    pinMode(PIN_BUZZER, OUTPUT);
  }
  gate.setPeriodHertz(50);
  gate.attach(PIN_SERVO, SERVO_MIN_US, SERVO_MAX_US);
  safeState();                                       // gate closed, everything off

  Serial.begin(BAUD);
  delay(100);
  Serial.printf("READY SMARTGUARD fw=%s reset=%s\n", FW_VERSION, resetReason());

  enableLoopWDT();                                   // loop() must return within 5 s or the chip resets
}

void loop() {
  readSerial();
  runTest();

  if (gateTimer && due(gateCloseAt)) setGate(false);
  if (ledTimer && due(ledOffAt)) { setLeds(false, false); ledTimer = false; }

  if (beeping) {                                     // beep pattern until beepEndAt
    if (due(beepEndAt)) stopBeeps();
    else if (due(beepToggleAt)) {
      setBuzzer(!buzzerOn);
      beepToggleAt = millis() + (buzzerOn ? BEEP_ON_MS : BEEP_OFF_MS);
    }
  }

  if (hostSeen && due(lastHostMs + HEARTBEAT_TIMEOUT_MS)) {   // desktop app went quiet
    safeState();
    hostSeen = false;
    digitalWrite(PIN_STATUS, LOW);
    Serial.println("EVT HOST_LOST");
  }
}
