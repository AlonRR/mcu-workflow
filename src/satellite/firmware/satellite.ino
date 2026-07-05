// ESP32 satellite firmware (deliverable #8).
//
// Provides the radio/GPIO instruments over USB-serial using the JSON-line
// protocol in ../protocol.md. Build with the Arduino ESP32 core **3.x**
// (the siggen uses the 3.x LEDC API: ledcAttach/ledcWrite/ledcDetach) +
// ArduinoJson. (A real on-device build is the verification; this sketch
// can't be compiled in the workflow's Linux sandbox.)
//
// Edition parity: implements ping/caps, wifi.*, gpio.*, and siggen.* from
// protocol.md. BLE is IDF-edition-only (NimBLE), so it is NOT advertised in
// caps here - hosts that gate on caps skip it instead of failing mid-test.
//
// Boards: any ESP32 / ESP32-S3 / ESP32-C3 dev board.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>

static const char* FW = "sat-0.1";

// Pin the signal generator currently drives, or -1. Detach before re-attach:
// core 3.x ledcAttach() fails on a pin that already has an LEDC channel.
static int siggen_pin = -1;

void sendObj(JsonDocument& doc) {
  serializeJson(doc, Serial);
  Serial.print('\n');
}

void ok(JsonDocument& res) { res["ok"] = true; }
void err(JsonDocument& res, const char* msg) { res["ok"] = false; res["error"] = msg; }
// String overload: ArduinoJson copies String values but stores const char* by
// pointer, so a formatted/temporary message (e.g. "unknown cmd: X") needs this
// one, not the const char* overload above, to avoid a dangling reference.
void err(JsonDocument& res, const String& msg) { res["ok"] = false; res["error"] = msg; }

void handle(const String& line) {
  StaticJsonDocument<512> req, res;
  if (deserializeJson(req, line)) { err(res, "bad json"); sendObj(res); return; }
  const char* cmd = req["cmd"] | "";

  if (!strcmp(cmd, "ping")) {
    ok(res); res["fw"] = FW;
  } else if (!strcmp(cmd, "caps")) {
    ok(res);
    // Only what this edition actually implements - the caps reply is the
    // contract hosts gate instruments on (no "ble": that's IDF-edition-only).
    JsonArray a = res.createNestedArray("capabilities");
    a.add("wifi"); a.add("gpio"); a.add("siggen");
  } else if (!strcmp(cmd, "wifi.ap_start")) {
    const char* ssid = req["ssid"] | "";
    const char* pass = req["password"] | "";
    int ch = req["channel"] | 1;
    WiFi.softAP(ssid, strlen(pass) ? pass : nullptr, ch);
    ok(res); res["ip"] = WiFi.softAPIP().toString();
  } else if (!strcmp(cmd, "wifi.ap_stop")) {
    WiFi.softAPdisconnect(true); ok(res);
  } else if (!strcmp(cmd, "wifi.scan")) {
    int n = WiFi.scanNetworks();
    ok(res);
    JsonArray nets = res.createNestedArray("networks");
    for (int i = 0; i < n; i++) {
      JsonObject o = nets.createNestedObject();
      o["ssid"] = WiFi.SSID(i); o["rssi"] = WiFi.RSSI(i);
    }
  } else if (!strcmp(cmd, "gpio.set")) {
    int pin = req["pin"] | -1; int val = req["value"] | 0;
    if (pin < 0) { err(res, "missing pin"); }
    else { pinMode(pin, OUTPUT); digitalWrite(pin, val ? HIGH : LOW); ok(res); }
  } else if (!strcmp(cmd, "gpio.get")) {
    int pin = req["pin"] | -1;
    if (pin < 0) { err(res, "missing pin"); }
    else { pinMode(pin, INPUT); ok(res); res["value"] = digitalRead(pin); }
  } else if (!strcmp(cmd, "siggen.start")) {
    // Square wave via LEDC, mirroring the IDF edition: 10-bit resolution,
    // duty in percent, reply {"ok":true,"freq":...,"duty":...}.
    int pin = req["pin"] | -1;
    int freq = req["freq"] | 1000;
    int duty = req["duty"] | 50;
    if (pin < 0) { err(res, "missing pin"); }
    else {
      if (freq < 1) freq = 1;
      if (duty < 0) duty = 0;
      if (duty > 100) duty = 100;
      if (siggen_pin >= 0) { ledcDetach(siggen_pin); siggen_pin = -1; }
      if (!ledcAttach(pin, freq, 10)) { err(res, "siggen attach failed"); }
      else {
        ledcWrite(pin, (1023 * duty) / 100);
        siggen_pin = pin;
        ok(res); res["freq"] = freq; res["duty"] = duty;
      }
    }
  } else if (!strcmp(cmd, "siggen.stop")) {
    if (siggen_pin >= 0) { ledcDetach(siggen_pin); siggen_pin = -1; }
    ok(res);
  } else if (!strcmp(cmd, "ble.scan") || !strcmp(cmd, "ble.write")) {
    // BLE handlers: add NimBLE-Arduino calls here (and add "ble" to caps).
    err(res, "ble not built in this image");
  } else {
    err(res, String("unknown cmd: ") + cmd);
  }
  sendObj(res);
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_AP_STA);
}

void loop() {
  static String buf;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') { handle(buf); buf = ""; }
    else if (c != '\r') { buf += c; }
  }
}
