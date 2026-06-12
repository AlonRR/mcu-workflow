// ESP32 satellite firmware (deliverable #8).
//
// Provides the radio/GPIO instruments over USB-serial using the JSON-line
// protocol in ../protocol.md. Build with the Arduino ESP32 core + ArduinoJson.
// (A real on-device build is the verification; this sketch can't be compiled
//  in the workflow's Linux sandbox.)
//
// Boards: any ESP32 / ESP32-S3 / ESP32-C3 dev board.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>

static const char* FW = "sat-0.1";

void sendObj(JsonDocument& doc) {
  serializeJson(doc, Serial);
  Serial.print('\n');
}

void ok(JsonDocument& res) { res["ok"] = true; }
void err(JsonDocument& res, const char* msg) { res["ok"] = false; res["error"] = msg; }

void handle(const String& line) {
  StaticJsonDocument<512> req, res;
  if (deserializeJson(req, line)) { err(res, "bad json"); sendObj(res); return; }
  const char* cmd = req["cmd"] | "";

  if (!strcmp(cmd, "ping")) {
    ok(res); res["fw"] = FW;
  } else if (!strcmp(cmd, "caps")) {
    ok(res);
    JsonArray a = res.createNestedArray("capabilities");
    a.add("wifi"); a.add("ble"); a.add("gpio");
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
  } else if (!strcmp(cmd, "ble.scan") || !strcmp(cmd, "ble.write")) {
    // BLE handlers: add NimBLE-Arduino calls here.
    err(res, "ble not built in this image");
  } else {
    String m = String("unknown cmd: ") + cmd;
    err(res, m.c_str());
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
