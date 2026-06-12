# Runbook — two ESP32-C3 Super Minis, end to end

This is the concrete bring-up for the hardware you have: **two ESP32-C3 Super
Minis**, one as the **satellite** (test instrument) and one as the **DUT**
(device under test). It is written so you can run the whole thing in
**simulation today** and flip one flag to drive the **real boards** when you are
ready.

The golden rule for "sim vs real" is a single flag:

| Stage | Simulated (no hardware) | Real hardware |
|---|---|---|
| pipeline | `mcuflow --sim run board-c3.yml` | `mcuflow run board-c3.yml --port COM4 --workbench http://127.0.0.1:8080` |
| workbench | `mcuflow workbench --satellite sim` | `mcuflow workbench --satellite COM5` |
| HIL | `mcuflow hil board-c3.yml` | `mcuflow hil board-c3.yml --workbench http://127.0.0.1:8080` |

---

## 0. Try it now — zero hardware

From the project folder (Windows: make sure `bin\` is on your PATH, or call
`python mcuflow\mcuflow.py`):

```
mcuflow --sim run board-schema/examples/board-c3.yml -o build-out/c3
```

You should see five green stages — validate, scaffold, build, flash, hil — and a
simulated C3 booting and joining the satellite's WiFi AP. That exercises the
exact same code paths the real run uses; only the bottom layer (idf.py, esptool,
the serial link) is stubbed. `python tests/smoke.py` runs the full regression.

---

## 1. Install on the board machine (Windows)

**The tool installs its own prerequisites.** Just run:

```
mcuflow doctor --fix      # pip deps + usbipd-win + Docker(if absent) + cage image
mcuflow doctor            # re-check: should read "readiness: ok"
```

`--fix` pip-installs pyyaml/jsonschema/pyserial, `winget`-installs **usbipd-win**
(USB→WSL2) and **Docker Desktop** if it is missing, and `docker pull`s the
ESP-IDF cage image so build/flash needs no host toolchain. The cage launcher has
the same self-install: `mcuflow up doctor --fix`.

Only Python 3.10+ must pre-exist (to run `mcuflow` at all). Everything else the
tool provisions. `usbipd bind` needs a one-time elevated prompt the first time
you attach a board.

Toolchains:
- **DUT** builds with **ESP-IDF v6.0** — provided by the cage image
  `espressif/idf:release-v6.0`, so you don't install it on the host.
- **Satellite** firmware (`satellite/firmware/satellite.ino`) is an **Arduino**
  sketch. The cage is an ESP-IDF image and has no Arduino toolchain, so the
  satellite is the one piece the cage can't build as-is. Two options:
  1. Flash the satellite **from the host** with `arduino-cli` (ESP32 core +
     ArduinoJson) once, and leave it running. Simplest today.
  2. Have me **rewrite the satellite as an ESP-IDF project** so the same cage
     builds both boards (cleaner; pending your go-ahead).

---

## 2. Identify the two boards

Plug both C3s in. On Windows each appears as a COM port (native USB-Serial/JTAG,
no CH340). Find them:

```
mcuflow up --os windows usb          # prints the usbipd hint
usbipd list                          # note the BUSID of each C3
```

Decide roles — e.g. the first you flash is the **satellite**, the second is the
**DUT**. Label the cables.

---

## 3. Wire the two boards together

Only needed for GPIO stimulus / auto-recovery (the satellite forcing the DUT
into download mode or resetting it). WiFi tests need no wires — they go over the
air.

```
  SATELLITE C3                         DUT C3 (under test)
  ------------                         -------------------
  GPIO2  (stimulus) --------------->   GPIO9  (BOOT strap)     # pull low = bootloader
  GPIO3  (reset)    --------------->   EN / RST pad            # pulse low = reset
  GND               <------------->    GND                     # common ground (required)
```

`board-c3.yml` already declares `rig.dut_boot_gpio: 9` and `rig.satellite:
required`. Pick any free satellite GPIOs for the two stimulus lines (above uses
2 and 3). **Common ground is mandatory** or the logic levels are meaningless.

C3 gotchas baked into `board-c3.yml`: GPIO8 = onboard LED (active-LOW), GPIO9 =
BOOT, buses kept off those pins. The native USB port re-enumerates on reset, so
expect the COM number to briefly drop/return around a flash.

---

## 4. Flash the satellite (once)

Option 1 (host, Arduino):

```
arduino-cli compile --fqbn esp32:esp32:esp32c3 satellite/firmware/satellite.ino
arduino-cli upload  --fqbn esp32:esp32:esp32c3 -p COM5 satellite/firmware/satellite.ino
```

Sanity-check it speaks the protocol:

```
mcuflow workbench --satellite COM5
# in another shell:
curl -X POST http://127.0.0.1:8080/api/satellite/ping      # -> {"ok":true,"fw":"sat-0.1"}
curl -X POST http://127.0.0.1:8080/api/wifi/scan
```

---

## 5. Open the cage with BOTH boards

```
mcuflow up --os windows --project . up --busid <DUT_BUSID> --busid <SAT_BUSID>
```

The launcher binds each board into WSL2 with usbipd and maps both into the
container as `/dev/ttyACM0` (DUT) and `/dev/ttyACM1` (satellite), drops
capabilities, runs non-root, and seats the agent. `--dry-run` first to read the
exact commands.

---

## 6. The real run

Inside the cage (or on the host if you installed ESP-IDF natively):

```
# start the instrument against the REAL satellite
mcuflow workbench --satellite /dev/ttyACM1 &

# build + flash + boot-test the DUT, driving the real satellite for radio tests
mcuflow run board-schema/examples/board-c3.yml \
        --port /dev/ttyACM0 \
        --workbench http://127.0.0.1:8080
```

What is real vs. still to come at this step:
- **Real now:** validate, scaffold, `idf.py build`, `esptool` flash, the DUT's
  `test_boots` (reads the chip's actual serial for `app_main started`), and the
  satellite's radios/GPIO driven for real through the workbench API.
- **Needs firmware:** the DUT's WiFi-join code is a TODO stub in the generated
  `main/main.c`. Until you fill it in, the real DUT won't actually join the AP —
  the `--sim` run models the *intended* behaviour so the harness is proven, but
  the on-silicon join is your firmware to write.
- **Next integration layer:** the `hil` verb currently asserts the join against a
  modelled DUT; wiring it to read the *real* DUT serial (so the join assertion is
  fully automated on hardware) is the remaining piece to make Section 6 push-button.

---

## 7. Where each promise is enforced

- Two boards pass through cleanly (Section 5) — `--device` ×2 / `--busid` ×2.
- The satellite is driven over one code path whether sim or real — only
  `--satellite sim|COMx` changes (Section 4/6).
- The boundary (egress allowlist, cap-drop, non-root) is the cage's, unchanged
  by any of this — see `ARCHITECTURE.md` §6–7 and `cage/`.
