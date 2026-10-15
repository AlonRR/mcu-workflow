# Runbook — two ESP32-C3 Super Minis, end to end

This is the concrete bring-up for the hardware you have: **two ESP32-C3 Super
Minis**, one as the **satellite** (test instrument) and one as the **DUT**
(device under test). It is written so you can run the whole thing in
**simulation today** and flip one flag to drive the **real boards** when you are
ready.

The golden rule for "sim vs real" is a single flag:

| Stage | Simulated (no hardware) | Real hardware |
|---|---|---|
| pipeline | `mcuflow --sim run board-c3.yml` | `mcuflow run board-c3.yml --port COM4 --workbench http://127.0.0.1:6283` |
| workbench | `mcuflow workbench --satellite sim` | `mcuflow workbench --satellite COM5` |
| HIL | `mcuflow hil board-c3.yml` | `mcuflow hil board-c3.yml --workbench http://127.0.0.1:6283` |

---

## 0. Try it now — zero hardware

From the project folder (Windows: make sure `bin\` is on your PATH, or call
`python mcuflow\mcuflow.py`):

```
mcuflow --sim run examples/board-c3.yml -o build-out/c3
```

You should see five green stages — validate, scaffold, build, flash, hil — and a
simulated C3 booting and joining the satellite's WiFi AP. That exercises the
exact same code paths the real run uses; only the bottom layer (idf.py, esptool,
the serial link) is stubbed. `pytest` runs the full regression.

---

## 1. Install on the board machine (Windows)

**The tool installs its own prerequisites.** Just run:

```
mcuflow doctor --fix      # uv .venv deps + usbipd-win + Docker(if absent) + cage image
mcuflow doctor            # re-check: should read "readiness: ok"
```

`--fix` installs the Python deps (pyyaml/jsonschema/pyserial/esptool) into a
uv-managed `.venv`, `winget`-installs **usbipd-win** (USB→WSL2) and **Docker
Desktop** if it is missing, and `docker pull`s the ESP-IDF cage image so
build/flash needs no host toolchain. The cage launcher has the same self-install:
`mcuflow up doctor --fix`.

**Nothing needs to pre-exist — not even Python.** The one-line installer brings
**uv**, which provides Python; the tool provisions everything else. `usbipd bind`
needs a one-time elevated prompt the first time you attach a board.

Toolchains:
- **DUT** builds with **ESP-IDF v6.0** — provided by the cage image
  `espressif/idf:release-v6.0`, so you don't install it on the host.
- **Satellite** firmware has two editions. The **ESP-IDF edition**
  (`src/satellite/firmware-idf/`) is preferred: the same cage toolchain builds
  both boards, so there's nothing extra to install. The **Arduino edition**
  (`src/satellite/firmware/satellite.ino`) remains as a no-IDF fallback — the
  cage has no Arduino toolchain, so that one must be flashed from the host with
  `arduino-cli` (ESP32 core + ArduinoJson).

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

`board-c3.yml` declares exactly this wiring: `rig.dut_boot_gpio: 2` and
`rig.dut_reset_gpio: 3`, plus `rig.satellite: required`. The `rig.*_gpio`
numbers are **satellite** pins (the satellite drives the DUT's lines through
them), never the DUT's own pin numbers. To use other free satellite GPIOs,
change the wires and those two numbers together. **Common ground is mandatory**
or the logic levels are meaningless.

Then prove the bench matches, before any test runs:

```
mcuflow commission examples/board-c3.yml --port <DUT_PORT> --satellite <SAT_PORT>
```

It reads the chip and flash size with esptool, checks the satellite's
capabilities, holds the BOOT line low and expects the DUT's ROM to report
`DOWNLOAD` at reset (and a normal flash boot once released), and holds EN low
expecting the DUT's USB port to drop and return. It resets the DUT, so it needs
`--port` and never guesses one: a connected ESP32 may belong to something else.

Add `--probe` to check the devices too. It builds a probe image from
`board.yml` (in the cage, or with a native ESP-IDF; cached under
`build-out/_probe/`), flashes it to the DUT, and reports for each I2C device
whether it answers at its address. A bus scan names any address that did
answer, which catches a BME280 strapped to 0x77 when the file says 0x76. The
DUT is left running the probe image, so flash the app next (`mcuflow run` does).

C3 gotchas baked into `board-c3.yml`: GPIO8 = onboard LED (active-LOW), GPIO9 =
BOOT, buses kept off those pins. The native USB port re-enumerates on reset, so
expect the COM number to briefly drop/return around a flash.

---

## 4. Flash the satellite (once)

Preferred (ESP-IDF — same toolchain as the DUT, builds in the cage):

```
cd src/satellite/firmware-idf
idf.py set-target esp32c3
idf.py -p COM5 flash                                        # fw reports "sat-idf-0.1"
```

Fallback (host, Arduino):

```
arduino-cli compile --fqbn esp32:esp32:esp32c3 src/satellite/firmware/satellite.ino
arduino-cli upload  --fqbn esp32:esp32:esp32c3 -p COM5 src/satellite/firmware/satellite.ino  # fw reports "sat-0.1"
```

Sanity-check it speaks the protocol (the `fw` string tells you which edition is on the board):

```
mcuflow workbench --satellite COM5
# in another shell:
curl -X POST http://127.0.0.1:6283/api/satellite/ping      # -> {"ok":true,"fw":"sat-idf-0.1"}
curl -X POST http://127.0.0.1:6283/api/wifi/scan
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
mcuflow run examples/board-c3.yml \
        --port /dev/ttyACM0 \
        --workbench http://127.0.0.1:6283
```

All five stages are green on real silicon (proven on the two C3s — see
`agents/handoff.md`, session 3):
- **Real now:** validate, scaffold, `idf.py build` (in the cage), `esptool` flash
  from the host, and an on-silicon HIL — for `wifi` boards the scaffold emits real
  WiFi-join firmware (the DUT joins the satellite AP and prints
  `wifi: connected to '<ssid>', got ip ...`), and the `hil` verb reads the **real**
  DUT serial to confirm both `app_main started` and that join line while the real
  satellite AP is up.
- **Commission (15 Oct 2026):** `mcuflow commission` (§3) passes in the
  simulator. Of what it parses, only esptool's chip-type header and the ROM's
  app-boot line were captured from a real C3; the `DOWNLOAD` boot line and
  esptool's `Detected flash size:` line follow their documented formats but were
  not captured. Its BOOT/EN wire checks have **not yet run on the two C3s**: do
  that before trusting a `gpio_stimulus` PASS, which has no readback.
  The `--probe` image compiles cleanly in the ESP-IDF v6.0 cage for both
  example boards (C3 and S3, 0 warnings, 15 Oct 2026) but has not yet run on
  hardware.
- **RF-proximity gotcha:** two PCB-antenna C3s sitting inches apart desense each
  other and the join loops at 802.11 auth (`reason=2`). Keep them ~0.5 m apart. If
  a join ever flaps, check board spacing first.

---

## 7. Where each promise is enforced

- Two boards pass through cleanly (Section 5) — `--device` ×2 / `--busid` ×2.
- The satellite is driven over one code path whether sim or real — only
  `--satellite sim|COMx` changes (Section 4/6).
- The boundary (egress allowlist, cap-drop, non-root) is the cage's, unchanged
  by any of this — see `docs/architecture.md` §6–7 and `deploy/cage/`.
