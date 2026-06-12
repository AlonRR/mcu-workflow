// ESP32 satellite firmware - ESP-IDF edition (deliverable #8, IDF build).
//
// Same JSON-line protocol as ../protocol.md and the Arduino sketch, but built
// with ESP-IDF so the cage's single toolchain builds BOTH boards (DUT + this
// satellite). Channel: the C3 Super Mini's native USB-Serial/JTAG. One JSON
// request object per line in; one JSON response object per line out.
//
// Commands: ping, caps, wifi.ap_start, wifi.ap_stop, wifi.scan,
//           gpio.set, gpio.get   (ble.* -> "ble not built in this image")
//
// NOTE: this is real firmware; it must be built/flashed on hardware to verify
// (the workflow's Linux sandbox cannot compile it). If a component REQUIRES
// name differs on your ESP-IDF point release, the build error names it - fix in
// main/CMakeLists.txt. Target: esp32c3 (idf.py set-target esp32c3).

#include <string.h>
#include <stdlib.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "driver/gpio.h"
#include "driver/usb_serial_jtag.h"
#include "cJSON.h"

#define FW "sat-idf-0.1"
#define SAT_LINE_MAX 512

static bool s_ap_up = false;

// --- transport: one line out over USB-Serial/JTAG ---------------------------
static void send_line(cJSON *res) {
    char *txt = cJSON_PrintUnformatted(res);
    if (txt) {
        usb_serial_jtag_write_bytes((const uint8_t *)txt, strlen(txt), portMAX_DELAY);
        usb_serial_jtag_write_bytes((const uint8_t *)"\n", 1, portMAX_DELAY);
        cJSON_free(txt);
    }
}

static void reply_ok(void) {
    cJSON *r = cJSON_CreateObject();
    cJSON_AddBoolToObject(r, "ok", true);
    send_line(r);
    cJSON_Delete(r);
}

static void reply_err(const char *msg) {
    cJSON *r = cJSON_CreateObject();
    cJSON_AddBoolToObject(r, "ok", false);
    cJSON_AddStringToObject(r, "error", msg);
    send_line(r);
    cJSON_Delete(r);
}

// --- wifi -------------------------------------------------------------------
static void wifi_init_once(void) {
    static bool done = false;
    if (done) return;
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_ap();
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    ESP_ERROR_CHECK(esp_wifi_start());
    done = true;
}

static void handle_ap_start(cJSON *req) {
    wifi_init_once();
    const cJSON *jssid = cJSON_GetObjectItem(req, "ssid");
    if (!cJSON_IsString(jssid) || strlen(jssid->valuestring) == 0) {
        reply_err("missing ssid");
        return;
    }
    const cJSON *jpass = cJSON_GetObjectItem(req, "password");
    const cJSON *jchan = cJSON_GetObjectItem(req, "channel");

    wifi_config_t ap = {0};
    strlcpy((char *)ap.ap.ssid, jssid->valuestring, sizeof(ap.ap.ssid));
    ap.ap.ssid_len = strlen((char *)ap.ap.ssid);
    ap.ap.max_connection = 4;
    ap.ap.channel = cJSON_IsNumber(jchan) ? (uint8_t)jchan->valueint : 1;
    if (cJSON_IsString(jpass) && strlen(jpass->valuestring) >= 8) {
        strlcpy((char *)ap.ap.password, jpass->valuestring, sizeof(ap.ap.password));
        ap.ap.authmode = WIFI_AUTH_WPA2_PSK;
    } else {
        ap.ap.authmode = WIFI_AUTH_OPEN;
    }
    // ESP-IDF v6.0's softAP defaults can require PMF; a plain WPA2-PSK STA then
    // fails authentication (disconnect reason 2). Advertise PMF as optional so
    // both PMF and non-PMF stations can associate.
    ap.ap.pmf_cfg.capable = true;
    ap.ap.pmf_cfg.required = false;
    // Raise the AP in AP-only mode: in APSTA the single radio is shared with the
    // (idle) STA, which can disrupt the auth handshake of a joining station
    // (also seen as disconnect reason 2). scan switches back to STA when needed.
    esp_wifi_set_mode(WIFI_MODE_AP);
    if (esp_wifi_set_config(WIFI_IF_AP, &ap) != ESP_OK) {
        reply_err("ap config failed");
        return;
    }
    s_ap_up = true;
    cJSON *r = cJSON_CreateObject();
    cJSON_AddBoolToObject(r, "ok", true);
    cJSON_AddStringToObject(r, "ip", "192.168.4.1");   // default softAP gateway
    send_line(r);
    cJSON_Delete(r);
}

static void handle_ap_stop(void) {
    wifi_config_t empty = {0};
    esp_wifi_set_config(WIFI_IF_AP, &empty);
    s_ap_up = false;
    reply_ok();
}

static void handle_scan(void) {
    wifi_init_once();
    esp_wifi_set_mode(WIFI_MODE_APSTA);   // scanning needs the STA interface
    wifi_scan_config_t sc = {0};
    if (esp_wifi_scan_start(&sc, true) != ESP_OK) {
        reply_err("scan failed");
        return;
    }
    uint16_t n = 0;
    esp_wifi_scan_get_ap_num(&n);
    if (n > 20) n = 20;
    wifi_ap_record_t *recs = calloc(n, sizeof(wifi_ap_record_t));
    if (n && !recs) { reply_err("oom"); return; }
    esp_wifi_scan_get_ap_records(&n, recs);

    cJSON *r = cJSON_CreateObject();
    cJSON_AddBoolToObject(r, "ok", true);
    cJSON *arr = cJSON_AddArrayToObject(r, "networks");
    for (uint16_t i = 0; i < n; i++) {
        cJSON *o = cJSON_CreateObject();
        cJSON_AddStringToObject(o, "ssid", (const char *)recs[i].ssid);
        cJSON_AddNumberToObject(o, "rssi", recs[i].rssi);
        cJSON_AddItemToArray(arr, o);
    }
    send_line(r);
    cJSON_Delete(r);
    free(recs);
}

// --- gpio -------------------------------------------------------------------
static void handle_gpio_set(cJSON *req) {
    const cJSON *jpin = cJSON_GetObjectItem(req, "pin");
    const cJSON *jval = cJSON_GetObjectItem(req, "value");
    if (!cJSON_IsNumber(jpin)) { reply_err("missing pin"); return; }
    int pin = jpin->valueint;
    int val = cJSON_IsNumber(jval) ? jval->valueint : 0;
    gpio_reset_pin(pin);
    gpio_set_direction(pin, GPIO_MODE_OUTPUT);
    gpio_set_level(pin, val ? 1 : 0);
    reply_ok();
}

static void handle_gpio_get(cJSON *req) {
    const cJSON *jpin = cJSON_GetObjectItem(req, "pin");
    if (!cJSON_IsNumber(jpin)) { reply_err("missing pin"); return; }
    int pin = jpin->valueint;
    gpio_reset_pin(pin);
    gpio_set_direction(pin, GPIO_MODE_INPUT);
    cJSON *r = cJSON_CreateObject();
    cJSON_AddBoolToObject(r, "ok", true);
    cJSON_AddNumberToObject(r, "value", gpio_get_level(pin));
    send_line(r);
    cJSON_Delete(r);
}

// --- dispatch ---------------------------------------------------------------
static void handle_line(char *line) {
    cJSON *req = cJSON_Parse(line);
    if (!req) { reply_err("bad json"); return; }
    const cJSON *jcmd = cJSON_GetObjectItem(req, "cmd");
    const char *cmd = cJSON_IsString(jcmd) ? jcmd->valuestring : "";

    if      (!strcmp(cmd, "ping")) {
        cJSON *r = cJSON_CreateObject();
        cJSON_AddBoolToObject(r, "ok", true);
        cJSON_AddStringToObject(r, "fw", FW);
        send_line(r); cJSON_Delete(r);
    } else if (!strcmp(cmd, "caps")) {
        cJSON *r = cJSON_CreateObject();
        cJSON_AddBoolToObject(r, "ok", true);
        cJSON *a = cJSON_AddArrayToObject(r, "capabilities");
        cJSON_AddItemToArray(a, cJSON_CreateString("wifi"));
        cJSON_AddItemToArray(a, cJSON_CreateString("gpio"));
        send_line(r); cJSON_Delete(r);
    } else if (!strcmp(cmd, "wifi.ap_start")) {
        handle_ap_start(req);
    } else if (!strcmp(cmd, "wifi.ap_stop")) {
        handle_ap_stop();
    } else if (!strcmp(cmd, "wifi.scan")) {
        handle_scan();
    } else if (!strcmp(cmd, "gpio.set")) {
        handle_gpio_set(req);
    } else if (!strcmp(cmd, "gpio.get")) {
        handle_gpio_get(req);
    } else if (!strcmp(cmd, "ble.scan") || !strcmp(cmd, "ble.write")) {
        reply_err("ble not built in this image");
    } else {
        char msg[64];
        snprintf(msg, sizeof(msg), "unknown cmd: %s", cmd);
        reply_err(msg);
    }
    cJSON_Delete(req);
}

void app_main(void) {
    esp_log_level_set("*", ESP_LOG_NONE);     // keep the protocol channel clean
    esp_err_t nv = nvs_flash_init();
    if (nv == ESP_ERR_NVS_NO_FREE_PAGES || nv == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    usb_serial_jtag_driver_config_t ucfg = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
    usb_serial_jtag_driver_install(&ucfg);

    static char line[SAT_LINE_MAX];
    size_t len = 0;
    uint8_t ch;
    for (;;) {
        int n = usb_serial_jtag_read_bytes(&ch, 1, pdMS_TO_TICKS(100));
        if (n <= 0) continue;
        if (ch == '\n') {
            line[len] = '\0';
            if (len > 0) handle_line(line);
            len = 0;
        } else if (ch != '\r' && len < SAT_LINE_MAX - 1) {
            line[len++] = (char)ch;
        } else if (len >= SAT_LINE_MAX - 1) {
            len = 0;                            // overflow -> drop the line
        }
    }
}
