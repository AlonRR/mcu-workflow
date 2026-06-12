#!/usr/bin/env python3
"""
scaffold.py - turn a board.yml into a buildable ESP-IDF project.

Reads the single-source-of-truth contract (board.yml) and emits a real,
buildable project skeleton:

  <out>/
    CMakeLists.txt              top-level ESP-IDF project file
    sdkconfig.defaults          build overrides + power profile
    main/
      CMakeLists.txt            component registration
      idf_component.yml         deps (auto-filled from devices[].driver)
      main.c                    app_main with per-bus / per-device init stubs
    pytest_<project>.py         pytest-embedded HIL skeleton
    README.md

This is deliverable #3. It is the deterministic conductor's "scaffold" verb:
no model needed, same output every run. Run the board-schema validator first.

Exit codes: 0 ok, 2 usage / dependency / bad input.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _die(msg, code=2):
    print("error: " + msg, file=sys.stderr)
    raise SystemExit(code)


def _load_yaml(path):
    try:
        import yaml  # type: ignore
    except ImportError:
        _die("PyYAML is not installed. Run: pip install pyyaml")
    if not path.exists():
        _die("file not found: " + str(path))
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        _die("top level of board.yml must be a mapping.")
    return data


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print("  wrote " + str(path))


def classify_pins(pins):
    """Group pin entries by bus kind."""
    buses = {"i2c": [], "spi": [], "uart": [], "simple": []}
    for name, val in (pins or {}).items():
        if isinstance(val, dict):
            if name.startswith("i2c"):
                buses["i2c"].append((name, val))
            elif name.startswith("spi"):
                buses["spi"].append((name, val))
            elif name.startswith("uart"):
                buses["uart"].append((name, val))
            else:
                buses["simple"].append((name, val))
        elif isinstance(val, int) and not isinstance(val, bool):
            buses["simple"].append((name, val))
    return buses


def collect_deps(data):
    """Components + device drivers -> {name: version}."""
    deps = {}
    for item in data.get("components") or []:
        if isinstance(item, str):
            if ":" in item:
                n, v = item.split(":", 1)
                deps[n.strip()] = v.strip().strip('"')
            else:
                deps[item.strip()] = "*"
        elif isinstance(item, dict):
            for n, v in item.items():
                deps[n] = str(v)
    for dname, dev in (data.get("devices") or {}).items():
        drv = dev.get("driver")
        if drv and drv not in deps:
            deps[drv] = "*"
    return deps


def gen_top_cmake(project):
    return (
        "cmake_minimum_required(VERSION 3.16)\n"
        "include($ENV{IDF_PATH}/tools/cmake/project.cmake)\n"
        "project(" + project + ")\n"
    )


def gen_main_cmake(needs_wifi=False, buses=None):
    # ESP-IDF v6.0 split the monolithic `driver` component into per-peripheral
    # components, so require the specific ones whose headers main.c includes.
    buses = buses or {"i2c": [], "spi": [], "uart": []}
    reqs = ["esp_driver_gpio"]  # driver/gpio.h is always used
    if buses.get("i2c"):
        reqs.append("esp_driver_i2c")  # driver/i2c_master.h
    if buses.get("spi"):
        reqs.append("esp_driver_spi")  # driver/spi_master.h
    if buses.get("uart"):
        reqs.append("esp_driver_uart")  # driver/uart.h
    if needs_wifi:
        reqs += ["esp_wifi", "nvs_flash", "esp_netif", "esp_event"]
    reqs_line = "\n                       REQUIRES " + " ".join(reqs)
    return (
        'idf_component_register(SRCS "main.c"\n'
        '                       INCLUDE_DIRS "."' + reqs_line + ")\n"
    )


def gen_component_yml(deps):
    lines = ["dependencies:", '  idf: ">=5.0"']
    for n, v in deps.items():
        lines.append("  " + n + ': "' + v + '"')
    return "\n".join(lines) + "\n"


def gen_sdkconfig(data):
    lines = [
        "# Generated from board.yml (build.sdkconfig + power profile).",
        "# Review against your chip and ESP-IDF version.",
    ]
    for k, v in (data.get("build", {}).get("sdkconfig") or {}).items():
        if v is True:
            val = "y"
        elif v is False:
            val = "n"
        else:
            val = str(v)
        lines.append(str(k) + "=" + val)

    power = data.get("power") or {}
    if power:
        lines.append("")
        lines.append("# --- derived from power: ---")
        if power.get("sleep") in ("light", "deep"):
            lines.append("CONFIG_PM_ENABLE=y")
        if power.get("sleep") == "light" or power.get("light_sleep_on_idle"):
            lines.append("CONFIG_FREERTOS_USE_TICKLESS_IDLE=y")
        cf = power.get("cpu_freq_mhz")
        if cf:
            lines.append(
                "# Target CPU frequency "
                + str(cf)
                + " MHz (set CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_<n> for your chip)"
            )
            lines.append("CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ=" + str(cf))
    return "\n".join(lines) + "\n"


_WIFI_HELPER = r"""// --- WiFi STA join (generated because test.needs includes 'wifi') ----------
// Credentials match the workbench HIL convention (sim/hil.py defaults).
#define WIFI_SSID "mcuflow-test"
#define WIFI_PASS "password123"

static void on_wifi(void *arg, esp_event_base_t base, int32_t id, void *data) {
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *d = (wifi_event_sta_disconnected_t *)data;
        ESP_LOGW(TAG, "wifi: disconnected, reason=%d", d ? d->reason : -1);
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "wifi: connected to '%s', got ip " IPSTR, WIFI_SSID, IP2STR(&e->ip_info.ip));
    }
}

static void wifi_join(void) {
    esp_err_t nv = nvs_flash_init();
    if (nv == ESP_ERR_NVS_NO_FREE_PAGES || nv == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi, NULL, NULL);
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi, NULL, NULL);
    wifi_config_t wc = {0};
    strlcpy((char *)wc.sta.ssid, WIFI_SSID, sizeof(wc.sta.ssid));
    strlcpy((char *)wc.sta.password, WIFI_PASS, sizeof(wc.sta.password));
    // Accept an optional-PMF WPA2-PSK AP (matches the satellite). Without this,
    // ESP-IDF v6.0 PMF defaults can cause auth to fail (disconnect reason 2).
    wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    wc.sta.pmf_cfg.capable = true;
    wc.sta.pmf_cfg.required = false;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
}"""


def gen_main_c(data, buses, needs_wifi=False):
    project = data["meta"]["project"]
    boot = (data.get("test") or {}).get("boot_string", "app_main started")
    devices = data.get("devices") or {}

    inc = [
        "#include <stdio.h>",
        '#include "freertos/FreeRTOS.h"',
        '#include "freertos/task.h"',
        '#include "esp_log.h"',
        '#include "driver/gpio.h"',
    ]
    if buses["i2c"]:
        inc.append('#include "driver/i2c_master.h"')
    if buses["spi"]:
        inc.append('#include "driver/spi_master.h"')
    if buses["uart"]:
        inc.append('#include "driver/uart.h"')
    if needs_wifi:
        inc += [
            "#include <string.h>",
            '#include "nvs_flash.h"',
            '#include "esp_wifi.h"',
            '#include "esp_event.h"',
            '#include "esp_netif.h"',
        ]

    L = []
    L.extend(inc)
    L.append("")
    L.append('static const char *TAG = "' + project + '";')
    L.append("")

    # Per-bus init stubs (commented, pins filled in from board.yml).
    for name, cfg in buses["i2c"]:
        sda = cfg.get("sda")
        scl = cfg.get("scl")
        freq = cfg.get("freq_hz", 400000)
        L.append(
            "// I2C bus '"
            + name
            + "': SDA=GPIO"
            + str(sda)
            + ", SCL=GPIO"
            + str(scl)
            + ", "
            + str(freq)
            + " Hz"
        )
        L.append("// TODO: create with i2c_new_master_bus() then add each device.")
    for name, cfg in buses["spi"]:
        L.append(
            "// SPI bus '"
            + name
            + "': MOSI=GPIO"
            + str(cfg.get("mosi"))
            + ", MISO=GPIO"
            + str(cfg.get("miso"))
            + ", SCLK=GPIO"
            + str(cfg.get("sclk"))
        )
        L.append("// TODO: spi_bus_initialize() then spi_bus_add_device() per device.")
    for name, cfg in buses["uart"]:
        L.append(
            "// UART '"
            + name
            + "': TX=GPIO"
            + str(cfg.get("tx"))
            + ", RX=GPIO"
            + str(cfg.get("rx"))
        )

    # Device notes.
    if devices:
        L.append("")
        for dname, dev in devices.items():
            note = (
                "// device '" + dname + "': " + str(dev.get("part")) + " on " + str(dev.get("bus"))
            )
            if "address" in dev:
                note += ", addr=" + hex(dev["address"])
            if "cs" in dev:
                note += ", CS=GPIO" + str(dev["cs"])
            drv = dev.get("driver")
            if drv:
                note += "  (driver: " + drv + ")"
            L.append(note)

    # Find a status LED among the simple pins.
    led_pin = None
    for name, pin in buses["simple"]:
        if "led" in name.lower():
            led_pin = pin
            break

    L.append("")
    if needs_wifi:
        L.append(_WIFI_HELPER)
        L.append("")
    L.append("void app_main(void)")
    L.append("{")
    L.append('    ESP_LOGI(TAG, "' + boot + '");')
    L.append("")
    if needs_wifi:
        L.append("    wifi_join();   // join the satellite AP (workbench HIL)")
        L.append("")
    if led_pin is not None:
        L.append("    // status LED")
        L.append("    gpio_reset_pin(" + str(led_pin) + ");")
        L.append("    gpio_set_direction(" + str(led_pin) + ", GPIO_MODE_OUTPUT);")
        L.append("    bool on = false;")
        L.append("    while (1) {")
        L.append("        on = !on;")
        L.append("        gpio_set_level(" + str(led_pin) + ", on);")
        L.append("        vTaskDelay(pdMS_TO_TICKS(500));")
        L.append("    }")
    else:
        L.append("    while (1) {")
        L.append('        ESP_LOGI(TAG, "alive");')
        L.append("        vTaskDelay(pdMS_TO_TICKS(1000));")
        L.append("    }")
    L.append("}")
    return "\n".join(L) + "\n"


def gen_pytest(data):
    project = data["meta"]["project"]
    chip = data["meta"]["chip"]
    test = data.get("test") or {}
    boot = test.get("boot_string", "app_main started")
    needs = test.get("needs") or []

    L = [
        '"""HIL test skeleton for ' + project + " (pytest-embedded).",
        "",
        "Run on real hardware:  pytest --target " + chip + " " + "pytest_" + project + ".py",
    ]
    if needs:
        L.append(
            "Instruments this suite needs: "
            + ", ".join(needs)
            + " (route to a runner/workbench that advertises them)."
        )
    L.append('"""')
    L.append("import pytest")
    L.append("")
    L.append("@pytest.mark." + chip)
    L.append("def test_boots(dut):")
    L.append('    """Flash (handled by the fixture) and confirm the boot string."""')
    L.append('    dut.expect("' + boot + '", timeout=30)')
    L.append("")
    if "wifi" in needs:
        L.append("# @pytest.mark." + chip)
        L.append("# def test_wifi_provision(dut, workbench):")
        L.append("#     workbench.ap_start('TestAP', 'password123')")
        L.append("#     ... drive provisioning, assert the DUT joins ...")
    return "\n".join(L) + "\n"


def gen_readme(data):
    project = data["meta"]["project"]
    chip = data["meta"]["chip"]
    return (
        "# " + project + "\n\n"
        "Generated from `board.yml` by the micro-controller workflow scaffold (#3).\n\n"
        "## Build\n\n"
        "```bash\n"
        "idf.py set-target " + chip + "\n"
        "idf.py build\n"
        "idf.py -p <PORT> flash monitor\n"
        "```\n\n"
        "`main/main.c` contains init stubs for the buses and devices declared in "
        "`board.yml` - fill them in. `pytest_" + project + ".py` is the HIL test skeleton.\n"
    )


def _scaffold_esp_idf(data, out_dir):
    project = data["meta"]["project"]
    buses = classify_pins(data.get("pins"))
    deps = collect_deps(data)
    needs_wifi = "wifi" in ((data.get("test") or {}).get("needs") or [])

    out = Path(out_dir)
    print("Scaffolding ESP-IDF project '" + project + "' into " + str(out))
    _write(out / "CMakeLists.txt", gen_top_cmake(project))
    _write(out / "sdkconfig.defaults", gen_sdkconfig(data))
    _write(out / "main" / "CMakeLists.txt", gen_main_cmake(needs_wifi, buses))
    _write(out / "main" / "idf_component.yml", gen_component_yml(deps))
    _write(out / "main" / "main.c", gen_main_c(data, buses, needs_wifi))
    _write(out / ("pytest_" + project + ".py"), gen_pytest(data))
    _write(out / "README.md", gen_readme(data))
    print(
        "Done. "
        + str(len(deps))
        + " dependency(ies); "
        + str(sum(len(v) for v in buses.values()))
        + " pin group(s)."
    )
    return 0


# meta.platform -> project generator. Adding a platform later is a new entry here
# (plus its adapter in src/adapters/); nothing else in the workflow changes.
_GENERATORS = {"esp32": _scaffold_esp_idf}


def scaffold(board_path, out_dir):
    data = _load_yaml(board_path)
    if "meta" not in data or "project" not in data["meta"]:
        _die("board.yml needs meta.project (run the validator first).")
    platform = data["meta"].get("platform", "esp32")
    gen = _GENERATORS.get(platform)
    if gen is None:
        _die(
            "no scaffold generator for platform '"
            + platform
            + "' yet (implemented: "
            + ", ".join(sorted(_GENERATORS))
            + "). Register one in scaffold.py to add support.",
            code=2,
        )
    return gen(data, out_dir)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scaffold an ESP-IDF project from a board.yml.")
    ap.add_argument("board", type=Path, help="path to board.yml")
    ap.add_argument(
        "-o", "--out", type=Path, default=None, help="output directory (default: ./<project>)"
    )
    args = ap.parse_args(argv)
    data = _load_yaml(args.board)
    project = (data.get("meta") or {}).get("project", "project")
    out = args.out or Path(project)
    return scaffold(args.board, out)


if __name__ == "__main__":
    raise SystemExit(main())
