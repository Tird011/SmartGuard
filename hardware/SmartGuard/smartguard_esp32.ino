//Backup lang to para sa hardware code pero iuupdate pa to once na maconect na sa breadboard ang iot
/*
 * SmartGuard-Vision ESP32 firmware
 *
 * Controls the checkpoint gate servo, green/red status LEDs and warning buzzer.
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
 *   STATUS      STATUS gate=<open|closed> green=<0|1> red=<0|1> buzzer=<0|1>
 *   every accepted command -> "OK <CMD>", unknown -> "ERR UNKNOWN"
 *
 * Safety: the gate is closed on boot. If the desktop app goes silent for
 * HEARTBEAT_TIMEOUT_MS (app crash, cable pulled) everything returns to SAFE.
 * Everything is non-blocking (millis timers), so serial stays responsive.
 *
 * Library: "ESP32Servo" (Arduino Library Manager).
 * WIRING NOTE: power the servo from its own 5V supply (share GND with the ESP32).
 * Powering it from the ESP32's pin can brown the board out when the gate moves.
 */
#include <ESP32Servo.h>

// ---------------- EDIT THESE TO MATCH YOUR WIRING ----------------
const uint8_t PIN_SERVO     = 18;
const uint8_t PIN_LED_GREEN = 26;
const uint8_t PIN_LED_RED   = 27;
const uint8_t PIN_BUZZER    = 25;   // active buzzer (HIGH = sound)

const int SERVO_CLOSED_DEG = 0;
const int SERVO_OPEN_DEG   = 90;

const uint32_t GATE_OPEN_MS          = 5000;   // how long the gate stays open
const uint32_t WARN_MS               = 3000;   // how long the warning lasts
const uint32_t BEEP_ON_MS            = 150;
const uint32_t BEEP_OFF_MS           = 100;
const uint32_t HEARTBEAT_TIMEOUT_MS  = 10000;  // host silent this long -> SAFE
// -----------------------------------------------------------------

Servo gate;

bool gateOpen = false, gateTimer = false;      uint32_t gateCloseAt = 0;
bool greenOn = false, redOn = false;
bool ledTimer = false;                         uint32_t ledOffAt = 0;
bool beeping = false, buzzerOn = false;        uint32_t beepEndAt = 0, beepToggleAt = 0;
bool hostSeen = false;                         uint32_t lastHostMs = 0;

char buf[24];
uint8_t len = 0;
bool overflow = false;

static inline bool due(uint32_t t) { return (int32_t)(millis() - t) >= 0; }

void setBuzzer(bool on) { buzzerOn = on; digitalWrite(PIN_BUZZER, on ? HIGH : LOW); }

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
  setGate(false);
  setLeds(false, false);
  stopBeeps();
  ledTimer = false;
}

void handleCommand(const char *cmd) {
  if (strcmp(cmd, "PING") == 0) { Serial.println("PONG"); return; }

  if (strcmp(cmd, "PASS") == 0) {
    setLeds(true, false);
    stopBeeps();
    setGate(true);
    ledTimer = true; ledOffAt = gateCloseAt;
  } else if (strcmp(cmd, "WARN") == 0) {
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
  } else if (strcmp(cmd, "STATUS") == 0) {
    Serial.printf("STATUS gate=%s green=%d red=%d buzzer=%d\n",
                  gateOpen ? "open" : "closed", greenOn, redOn, buzzerOn);
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
        lastHostMs = millis(); hostSeen = true;   // any valid line counts as a heartbeat
        handleCommand(buf);
      }
      len = 0;
    } else if (len < sizeof(buf) - 1) {
      buf[len++] = toupper(c);
    } else {
      overflow = true;                             // discard the rest of this line
    }
  }
}

void setup() {
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  gate.setPeriodHertz(50);
  gate.attach(PIN_SERVO, 500, 2400);
  safeState();                                     // gate closed, everything off
  Serial.begin(115200);
  delay(100);
  Serial.println("READY");
}

void loop() {
  readSerial();

  if (gateTimer && due(gateCloseAt)) setGate(false);
  if (ledTimer && due(ledOffAt)) { setLeds(false, false); ledTimer = false; }

  if (beeping) {                                   // beep pattern until beepEndAt
    if (due(beepEndAt)) stopBeeps();
    else if (due(beepToggleAt)) {
      setBuzzer(!buzzerOn);
      beepToggleAt = millis() + (buzzerOn ? BEEP_ON_MS : BEEP_OFF_MS);
    }
  }

  if (hostSeen && due(lastHostMs + HEARTBEAT_TIMEOUT_MS)) {   // desktop app went quiet
    safeState();
    hostSeen = false;
    Serial.println("EVT HOST_LOST");
  }
}