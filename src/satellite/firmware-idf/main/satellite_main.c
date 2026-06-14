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
#include "driver/ledc.h"
#include "freertos/semphr.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/ble_gap.h"
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

// --- signal generator (PWM) -------------------------------------------------
// One LEDC timer+channel drives a square wave on a pin: siggen.start {pin, freq,
// duty%}, siggen.stop. 10-bit resolution (duty 0..1023 maps from 0..100%).
static void handle_siggen_start(cJSON *req) {
    const cJSON *jpin = cJSON_GetObjectItem(req, "pin");
    if (!cJSON_IsNumber(jpin)) { reply_err("missing pin"); return; }
    const cJSON *jfreq = cJSON_GetObjectItem(req, "freq");
    const cJSON *jduty = cJSON_GetObjectItem(req, "duty");
    int pin = jpin->valueint;
    int freq = cJSON_IsNumber(jfreq) ? jfreq->valueint : 1000;
    int duty_pct = cJSON_IsNumber(jduty) ? jduty->valueint : 50;
    if (freq < 1) freq = 1;
    if (duty_pct < 0) duty_pct = 0;
    if (duty_pct > 100) duty_pct = 100;

    ledc_timer_config_t tcfg = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_10_BIT,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = freq,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    if (ledc_timer_config(&tcfg) != ESP_OK) { reply_err("siggen timer config failed"); return; }
    ledc_channel_config_t ccfg = {
        .gpio_num = pin,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0,
        .timer_sel = LEDC_TIMER_0,
        .duty = (uint32_t)((1023 * duty_pct) / 100),
        .hpoint = 0,
    };
    if (ledc_channel_config(&ccfg) != ESP_OK) { reply_err("siggen channel config failed"); return; }
    cJSON *r = cJSON_CreateObject();
    cJSON_AddBoolToObject(r, "ok", true);
    cJSON_AddNumberToObject(r, "freq", freq);
    cJSON_AddNumberToObject(r, "duty", duty_pct);
    send_line(r);
    cJSON_Delete(r);
}

static void handle_siggen_stop(void) {
    ledc_stop(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0);
    reply_ok();
}

// --- ble (NimBLE observer: ble.scan) ----------------------------------------
#define BLE_MAX_RESULTS 24
typedef struct {
    char addr[18];
    char name[32];
    int rssi;
} ble_dev_t;
static ble_dev_t s_ble[BLE_MAX_RESULTS];
static int s_ble_n = 0;
static SemaphoreHandle_t s_ble_mtx;
static SemaphoreHandle_t s_ble_done;
static volatile bool s_ble_ready = false;

static void ble_addr_str(const ble_addr_t *a, char *out) {
    const uint8_t *v = a->val;  // NimBLE stores the address little-endian
    sprintf(out, "%02x:%02x:%02x:%02x:%02x:%02x", v[5], v[4], v[3], v[2], v[1], v[0]);
}

static int ble_gap_event(struct ble_gap_event *event, void *arg) {
    if (event->type == BLE_GAP_EVENT_DISC) {
        char addr[18];
        ble_addr_str(&event->disc.addr, addr);
        xSemaphoreTake(s_ble_mtx, portMAX_DELAY);
        bool seen = false;
        for (int i = 0; i < s_ble_n; i++) {
            if (!strcmp(s_ble[i].addr, addr)) { seen = true; break; }
        }
        if (!seen && s_ble_n < BLE_MAX_RESULTS) {
            ble_dev_t *d = &s_ble[s_ble_n++];
            strlcpy(d->addr, addr, sizeof(d->addr));
            d->rssi = event->disc.rssi;
            d->name[0] = '\0';
            struct ble_hs_adv_fields f;
            if (ble_hs_adv_parse_fields(&f, event->disc.data, event->disc.length_data) == 0 &&
                f.name_len > 0) {
                int n = f.name_len < (int)sizeof(d->name) - 1 ? f.name_len : (int)sizeof(d->name) - 1;
                memcpy(d->name, f.name, n);
                d->name[n] = '\0';
            }
        }
        xSemaphoreGive(s_ble_mtx);
    } else if (event->type == BLE_GAP_EVENT_DISC_COMPLETE) {
        xSemaphoreGive(s_ble_done);
    }
    return 0;
}

static void ble_on_sync(void) { s_ble_ready = true; }
static void ble_host_task(void *param) {
    nimble_port_run();
    nimble_port_freertos_deinit();
}

static void ble_init_once(void) {
    static bool done = false;
    if (done) return;
    s_ble_mtx = xSemaphoreCreateMutex();
    s_ble_done = xSemaphoreCreateBinary();
    nimble_port_init();
    ble_hs_cfg.sync_cb = ble_on_sync;
    nimble_port_freertos_init(ble_host_task);
    done = true;
}

static void handle_ble_scan(cJSON *req) {
    ble_init_once();
    const cJSON *jt = cJSON_GetObjectItem(req, "timeout");
    int secs = cJSON_IsNumber(jt) ? jt->valueint : 4;
    if (secs < 1) secs = 1;
    if (secs > 15) secs = 15;
    for (int i = 0; i < 150 && !s_ble_ready; i++) vTaskDelay(pdMS_TO_TICKS(20));
    if (!s_ble_ready) { reply_err("ble stack not ready"); return; }

    xSemaphoreTake(s_ble_mtx, portMAX_DELAY);
    s_ble_n = 0;
    xSemaphoreGive(s_ble_mtx);

    uint8_t own_addr_type;
    if (ble_hs_id_infer_auto(0, &own_addr_type) != 0) { reply_err("ble no identity"); return; }
    struct ble_gap_disc_params dp = {0};
    dp.passive = 1;
    if (ble_gap_disc(own_addr_type, secs * 1000, &dp, ble_gap_event, NULL) != 0) {
        reply_err("ble scan start failed");
        return;
    }
    xSemaphoreTake(s_ble_done, pdMS_TO_TICKS(secs * 1000 + 1500));

    cJSON *r = cJSON_CreateObject();
    cJSON_AddBoolToObject(r, "ok", true);
    cJSON *arr = cJSON_AddArrayToObject(r, "devices");
    xSemaphoreTake(s_ble_mtx, portMAX_DELAY);
    for (int i = 0; i < s_ble_n; i++) {
        cJSON *o = cJSON_CreateObject();
        cJSON_AddStringToObject(o, "addr", s_ble[i].addr);
        cJSON_AddStringToObject(o, "name", s_ble[i].name);
        cJSON_AddNumberToObject(o, "rssi", s_ble[i].rssi);
        cJSON_AddItemToArray(arr, o);
    }
    xSemaphoreGive(s_ble_mtx);
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
        cJSON_AddItemToArray(a, cJSON_CreateString("siggen"));
        cJSON_AddItemToArray(a, cJSON_CreateString("ble"));
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
    } else if (!strcmp(cmd, "siggen.start")) {
        handle_siggen_start(req);
    } else if (!strcmp(cmd, "siggen.stop")) {
        handle_siggen_stop();
    } else if (!strcmp(cmd, "ble.scan")) {
        handle_ble_scan(req);
    } else if (!strcmp(cmd, "ble.write")) {
        reply_err("ble.write not supported (scan/observer only)");
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
