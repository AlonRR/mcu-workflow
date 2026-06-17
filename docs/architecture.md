# Microcontroller Workflow — Architecture & Plan

*Draft v0.3 · 2026-06-11 · target-first: ESP32, designed to generalize*

## 1. Purpose

Build a layer of tooling that compresses the full microcontroller development loop — from hardware design and part selection through firmware implementation, build, flash, hardware-in-the-loop (HIL) testing, and a 3D-printable enclosure — into a small number of repeatable, automatable steps. ESP32 is the first concrete target, but every abstraction is chosen so that adding STM32, RP2040, AVR, or a Zephyr-based board later is an incremental change, not a rewrite.

The deliverable described here is the *plan*. The artifact it describes is a three-part bundle: a **skill** (the orchestration brain), a **thin CLI/library** (the deterministic verbs), and a **project template** (the known-good starting point). They are layered so each is useful on its own.

## 2. Design principles

The workflow is built around a few commitments. First, *wrap, don't reinvent*: Espressif already ships a mature toolchain (ESP-IDF v6.0, `idf.py`, the component manager, EIM, pytest-embedded, and — as of 2026 — two official MCP servers). The job is orchestration and ergonomics, not re-implementing a build system. Second, *every stage is a verb*: spec, scaffold, configure, build, flash, test, and report are each a discrete, scriptable operation with machine-readable output, so they can be chained by a human, a CI runner, or an AI agent identically. Third, *the hardware is the source of truth for testing*: host unit tests and QEMU are useful early gates, but the contract is HIL — firmware must run on a real board and report back. Fourth, *target-agnostic core, target-specific adapters*: a stable internal interface (`Board`, `Toolchain`, `Flasher`, `TestRunner`) keeps ESP32 specifics behind an adapter so a second ecosystem slots in beside it. Fifth, *separate deterministic orchestration from judgment*: the fixed pipeline (spec → scaffold → build → flash → test → report) is owned by a deterministic conductor — code, not the LLM — so it is reproducible, cheap, and runs headless in CI with no model present; Claude orchestrates only the judgment (ambiguous choices, error interpretation, recovery), calling the same verbs the conductor does rather than replacing them. Sixth, *modules expose contracts, the conductor wires them*: skills and libraries never call each other directly; each emits structured output the conductor (or Claude) composes — which is what lets the many planned skills/agents/libraries be developed and shipped independently.

## 3. The workflow loop

The loop runs from hardware design through test; stages 0–6 each consume a declarative input and emit a structured result.

**Design (Stage 0).** Before any firmware, the workflow helps turn a plain-language idea into a concrete, buyable hardware design — selecting a prebuilt board plus breakout modules where possible, producing a bill of materials with purchase links, a wiring guide, and a power budget, and (only when modules won't do) a custom PCB. It also generates a 3D-printable enclosure. This stage is novice-oriented and detailed below; its outputs populate `board.yml`.

**Specify.** A single declarative file (`board.yml`) captures the hardware contract: chip (e.g. `esp32s3`), board/devkit, pin assignments and peripheral roles (I2C SDA/SCL, SPI, UART, ADC channels), clock and flash settings, and which external components the project depends on. This is the human-authored anchor everything else derives from. Espressif's Documentation MCP server can be queried here to pull authoritative defaults (e.g. recommended I2C pins for a given chip) rather than guessing. For larger projects this pairs with a human-readable **Functional Specification Document (FSD)** — the reference implementation ships an `fsd-writer` skill for exactly this — so intended behavior, not just pinout, is written down before code and becomes the source the test suite is derived from. The full schema — adding `devices:`, `power:`, `hardware:` references, and `enclosure:` to the basics above — is given under "The board.yml contract" below.

**Scaffold.** From `board.yml`, generate a working ESP-IDF project: `CMakeLists.txt`, `sdkconfig.defaults`, an `idf_component.yml` manifest listing registry dependencies, a `main/` skeleton with the peripheral init stubs the spec implies, and a `pytest_*.py` HIL test skeleton. The scaffold is a real, buildable "hello peripherals" project from minute one.

**Configure.** Resolve dependencies via the IDF Component Manager (`idf.py add-dependency` / `update-dependencies`, sourced from the ESP Component Registry or Git), and set the target (`set_target`). `sdkconfig.defaults` keeps configuration reproducible and diffable rather than living in a binary menuconfig blob.

**Build.** `idf.py build` (CMake + Ninja under the hood). Output is parsed for size, warnings, and artifact presence so the result is a structured pass/fail with metrics, not a wall of log text.

**Flash & monitor.** Detect the connected device, flash, and capture the serial/JTAG stream. `esptool`/`idf.py flash monitor` provide the mechanics; the workflow wraps them so port discovery and log capture are automatic.

**Test (HIL) & report.** Run pytest-embedded against the real board, collect pass/fail plus captured device output, and emit a report. This is the stage that distinguishes "it compiled" from "it works." Crucially it covers more than logic: where the firmware communicates, the suite also exercises its **radios and protocols** — WiFi join/provisioning, BLE GATT, MQTT, OTA update — using the networked instruments described in Section 9.

### Stage 0 in depth — hardware & mechanical design (novice-friendly)

The design rule throughout: *buy a module, don't design a circuit* — drop to custom PCB only when there's a real reason. The assistant works as a ladder, easy to involved:

1. **Describe → parts list.** A plain-language goal ("battery temperature logger that posts over WiFi") becomes a concrete parts list built around a prebuilt dev board plus off-the-shelf breakout modules, so there are no loose passives to get right. Most prototypes can stop here.
2. **Parts list → buyable BOM.** Each part gets a purchase link: generic vendor *search* links instantly (AliExpress, Amazon), and specific products with live prices via a web lookup at request time. Exact product URLs and prices are never fabricated — they're fetched, since they go stale and vary by region.
3. **BOM → wiring guide.** A "module pin → board pin" connection diagram (including power and ground) generated from `pins:`/`devices:`. Because firmware is generated from the same file, the wiring and the code always agree.
4. **Power planning.** Estimates current draw, recommends a battery/regulator/USB supply, and feeds the `power:` section. Mains voltage and LiPo charging are flagged as needing caution rather than treated as beginner-safe.
5. **Custom PCB — only when justified.** When modules are too bulky/fragile or volume is high, it steps up to schematic + PCB in KiCad and produces fab files (JLCPCB/PCBWay). This is assistive, not push-button: a custom board should get an expert review before fab, and the tool says so every time.

Everything here flows back into `board.yml`: chosen parts become `devices:`, wiring becomes `pins:`, the supply becomes `power:`, and schematic/BOM/PCB links become the `hardware:` references. The boundary stays firm — *firmware-addressable* parts (a sensor's I²C address, a MOSFET gate driven by a GPIO) live in `board.yml`; pure passives, supply topology, and layout live in the EDA tool and are only referenced.

### The board.yml contract

Resolved (open item 1): `board.yml` is the **single source of truth** — one sectioned file from which scaffold, build, flash, test routing, enclosure, and wiring are all derived. Optional sections (`power:`, `devices:`, `hardware:`, `enclosure:`, `rig:`) are simply omitted when unused, with no penalty, so a blinky and a low-power sensor node use the same one file.

```yaml
# board.yml — the single source of truth for one project/target
meta:
  project: ios-voice-keyboard
  platform: esp32          # selects the adapter: esp32 | stm32 | rp2040 | zephyr
  chip: esp32s3            # set-target, OpenOCD cfg, QEMU model
  board: esp32-s3-devkitc-1
  framework: esp-idf       # esp-idf | platformio

build:
  sdkconfig:               # diffable overrides -> sdkconfig.defaults
    CONFIG_ESPTOOLPY_FLASHSIZE_8MB: y
  # toolchain / plugin / component versions live in the lockfile, not here

pins:                      # peripheral roles -> pin numbers (the buses)
  i2c0: { sda: 8, scl: 9, freq_hz: 400000 }
  spi2: { mosi: 11, miso: 13, sclk: 12 }
  uart0: { tx: 43, rx: 44 }
  status_led: 48

devices:                   # physical electronics the firmware talks to / controls
  temp:    { part: BME280,  bus: i2c0, address: 0x76, driver: espressif/bme280 }
  display: { part: SSD1306, bus: i2c0, address: 0x3C }
  sd_card: { part: microSD, bus: spi2, cs: 10 }
  motor:   { part: DRV8833, bus: gpio, pins: { in1: 4, in2: 5 } }   # MOSFET driver on GPIO -> a device

components:                # software driver deps -> idf_component.yml (auto-filled from devices[].driver)
  - espressif/led_strip: "^2.5.0"

power:                     # optional — low-power intent -> sdkconfig + init stubs
  sleep: deep              # none | light | deep
  cpu_freq_mhz: 80
  wake_sources: [gpio, timer]
  light_sleep_on_idle: true

hardware:                  # pointers to the upstream electrical design (referenced, not duplicated)
  schematic: docs/schematic.pdf
  pcb: hardware/board.kicad_pro
  bom: hardware/bom.csv
  power_source: "LiPo 3.7V 1200mAh"
  regulator: "AP2112-3.3"

enclosure:                 # optional — parametric build123d case for FDM
  style: snap-fit          # snap-fit | screw-down | rail-mount
  board_size_mm: { x: 25.5, y: 51, z: 1.6 }
  wall_mm: 2.0
  clearance_mm: 0.4        # FDM fit tolerance (printer-dependent)
  standoff_mm: 3
  cutouts:                 # openings that must reach the outside
    - { for: usb_c, side: -y }
    - { for: status_led, side: +z, type: lightpipe }

test:                      # which instruments the HIL suite needs -> routing (see §8/§9)
  needs: [serial, wifi, ble]
  boot_string: "app_main started"

rig:                       # optional physical wiring for stimulus / recovery
  dut_reset_gpio: 17
  dut_boot_gpio: 18
  satellite: required      # required | optional | none
```

### Enclosure: build123d → FDM

The enclosure is generated as parametric **build123d** (code CAD) from the `enclosure:` section, previewed live in VS Code via the **OCP CAD Viewer**, and exported to STL/3MF for FDM slicing. Code CAD is a deliberate choice: the model is versioned in git and regenerated whenever the board or its ports change, exactly like the firmware. The generator bakes in print-friendly defaults so a novice needn't know them — ≥2 mm walls, overhangs kept under ~45° to avoid supports, a tunable fit clearance, and screw-boss/snap-fit sizing. Honest limits: the model is only as good as the dimensions fed in (board footprint and port positions, from a datasheet or calipers), the real check is a **test print and fit** (the mechanical equivalent of HIL), and slicing/printing stays in your slicer (PrusaSlicer/Orca) — the workflow hands off a clean 3MF.

## 4. Tooling layer (ESP32, current as of June 2026)

| Concern | Tool | Notes |
|---|---|---|
| Install / env management | **EIM** (ESP-IDF Installation Manager) v0.8.1+ | Native installers across Win/macOS/Linux; supports headless install for CI; enable the `mcp` feature at install time. |
| Framework | **ESP-IDF v6.0** (stable, Mar 2026) | Picolibc replaces Newlib; legacy drivers (ADC/DAC/I2S/Timer/PCNT/MCPWM/RMT/TempSensor) removed — scaffolds must use current driver APIs. v5.2.7 is the latest 5.x for projects pinned to the old line. |
| Build / project CLI | **`idf.py`** (CMake + Ninja) | `set-target`, `build`, `flash`, `monitor`, `add-dependency`. Extensible with custom commands. |
| Dependencies | **IDF Component Manager** + ESP Component Registry | Declarative `idf_component.yml`; resolves at CMake time. |
| Build/flash automation for agents | **ESP-IDF Tools local MCP server** (`idf.py mcp-server`) | stdio server built into `idf.py`; exposes `set_target`, `build_project`, `flash_project`, `clean_project` and resources `project://config|status|devices`. Maps 1:1 to `idf.py`. |
| Knowledge / datasheets for agents | **Espressif Documentation MCP server** (`https://mcp.espressif.com/docs`) | Remote HTTP/SSE; grounds pin choices, API usage, and migration in current docs. |
| HIL & host testing | **pytest-embedded** (`pytest-embedded-idf`, `pytest-embedded-serial-esp`, `pytest-embedded-qemu`) | `--target esp32s3`; `target`/`env` markers route jobs to the right chip and runner; QEMU plugin for hardware-free pre-checks. |
| Flashing primitive | **esptool** | Underlies `idf.py flash`; used directly when finer control is needed. Supports `rfc2217://` URLs, enabling flash-over-network to a remote workbench. |
| Build alternative | **PlatformIO** | Many ESP32 projects use PlatformIO rather than raw ESP-IDF; the adapter and skills should auto-detect which lifecycle a project uses and drive either. |
| Networked test instrument | **Embedded workbench** (host-agnostic HTTP/RFC2217 service; see §9) | Exposes serial, JTAG/GDB, WiFi, BLE, MQTT, GPIO, UDP-log, and OTA over one LAN API so hardware is shared and reachable without USB passthrough. Runs on a Pi, mini-PC, laptop, or any Python+USB host; radio/GPIO via onboard, USB dongle, or ESP32 satellite. |
| Hardware design / BOM | **Agent + Docs MCP + web search** | Plain-language requirements → prebuilt-board-and-module selection → bill of materials with purchase links (vendor search links instant; specific products/prices via live lookup). |
| Schematic & PCB (custom only) | **KiCad** (+ JLCPCB/PCBWay fab) | Used only when off-the-shelf modules won't do; assistive, expert-reviewed before fabrication. |
| Enclosure CAD | **build123d** (code CAD) + **OCP CAD Viewer** (VS Code preview) | Parametric case generated from `enclosure:`; exports STL/3MF for FDM. |
| Slicing (FDM) | **PrusaSlicer / OrcaSlicer** (external) | Workflow hands off a clean 3MF; slicing/printing stays in the user's slicer. |

A key finding: Espressif now ships both an actions MCP server and a docs MCP server. The right architecture *consumes* these rather than duplicating them — the Tools server already gives an agent a controlled, real (not simulated) `set_target → build → flash → status` interface. Our skill orchestrates these plus the spec/scaffold/test stages they don't cover.

## 5. Automatic environment setup (virtual + physical)

The fastest loop is worthless if standing it up takes a day. Setup itself is a verb — `mcuflow env up` — that brings both the software environment and the physical test rig to a known-good state idempotently, and the same path runs on a developer laptop and a CI runner.

**Virtual (software) environment.** One command provisions a reproducible toolchain: a headless **EIM** install of a *pinned* ESP-IDF version (v6.0) with the `mcp` feature enabled, a Python virtualenv carrying the pinned pytest-embedded plugins (`-idf`, `-serial-esp`, `-qemu`), resolution of the project's `idf_component.yml` dependencies from the registry, and registration of both Espressif MCP servers with the agent client. The whole thing is driven from a lockfile (IDF version, plugin versions, component versions) so two machines resolve to byte-identical environments and upgrades are an explicit, diffable change rather than drift. Setup is detect-then-converge: an existing valid install is reused, a missing or mismatched one is repaired, nothing is reinstalled needlessly. For maximum reproducibility — and for CI — the same definition can target a container instead of the host, since Espressif publishes `espressif/idf` Docker images with the framework preinstalled; QEMU-only test gates then need no hardware at all. This is the default even on the developer's own desktop (see "The launcher" in Section 6): the toolchain lives in the containerized cage rather than polluting the host, and a one-step launcher hides the setup.

**Physical (hardware) environment.** The rig setup is the part most workflows leave manual, and it is exactly where HIL stalls. `env up` performs board discovery: enumerate USB serial devices, identify each attached chip (via `esptool` chip detection) and map it to its port, then write that inventory out as runner labels so CI can route `esp32s3 - generic` jobs to a machine that actually has an ESP32-S3. The goal is plug-and-go: attach a board by USB, run discovery once, and the runner is registered — no hand-editing of config. Where the rig includes switchable USB hubs or relay/USB-power control, the workflow drives them so boards can be power-cycled and hard-reset between tests without a human touching them, which is what makes unattended overnight HIL runs reliable. A round-trip self-test closes the setup: flash a known-good "heartbeat" firmware to each discovered board and confirm the expected serial output, so a bad cable or a wedged chip is caught at setup time, not three test failures later. The physical wiring contract (which board, which fixtures, which pins) lives in `board.yml` alongside the rest of the spec, so the rig is described declaratively rather than tribal-knowledge.

Both halves share one principle: setup is declarative, idempotent, and self-verifying, so "it works on my machine" and "it works on the runner" converge by construction.

## 6. Agent-ready environment (autonomous, sandboxed)

A central goal is that an AI coding agent — Claude Code or equivalent — can drive the whole loop unattended, with broad freedom to act. The way to grant "no limits" *safely* is not to remove guardrails everywhere; it is to give the agent a **contained, disposable sandbox** and then open everything up inside that boundary. Freedom and safety are reconciled by isolation, not by trust.

**The isolation boundary.** The agent runs inside the same provisioned environment from Section 5, but as a dedicated, throwaway unit — the `espressif/idf` container, a VM, or a dedicated bench/CI machine — that holds only this project, no production credentials, no payment or cloud-account access, and nothing whose loss would matter. Because the unit is reproducible from the lockfile and disposable, a worst-case agent action costs a `env up` rebuild, not real damage. That containment is what makes the permissions below acceptable.

**Bypass permissions inside the sandbox.** Within that boundary the agent runs without interactive approval prompts so it can iterate at full speed — e.g. Claude Code launched with `--dangerously-skip-permissions` (or, more granularly, a settings allowlist that pre-approves the project's commands: `idf.py`, `esptool`, `pytest`, git, file edits within the workspace). The deliberate choice is permissionless *inside* the cage, hardened *at* the cage wall. A short deny-list still applies to the genuinely irreversible and out-of-scope (no `git push --force` to shared remotes, no credential exfiltration, no destructive host-level commands) — these cost nothing in iteration speed and prevent the few actions a rebuild can't undo.

**Web access.** The agent needs the network: the ESP Component Registry and Git sources for dependencies, the Espressif Documentation MCP server for datasheets and APIs, and package indexes (PyPI) for tooling. The pattern is allowlisted egress — reach the hosts the workflow legitimately uses — rather than either a blanket block (which breaks dependency resolution) or unrestricted access (which widens the attack surface for prompt-injected instructions arriving via fetched content). For fully air-gapped CI, the lockfile plus a local mirror lets the same flow run with egress disabled entirely.

**Hardware-interface access.** This is the embedded-specific piece: the agent must reach the physical board. The sandbox is granted the device interfaces — the serial/USB ports (`/dev/ttyUSB*`, `/dev/ttyACM*`), USB bus for `esptool`/DFU, and JTAG/SWD probe for OpenOCD debugging — passed through explicitly (e.g. Docker `--device=/dev/ttyUSB0` and membership in the `dialout` group) rather than by running wide-open privileged. With interface access plus the Tools MCP server's `flash_project`/`project://devices`, the agent closes the loop end to end: edit code, build, flash a real chip, read back serial, and decide what to do next — autonomously. Hardware is inherently the safest thing to hand an agent: a devkit on a bench has no blast radius beyond itself, and the power-switching rig from Section 5 lets the agent recover a wedged board by power-cycling it instead of needing a human.

**What makes "no limits" safe, in one line.** The environment is isolated, reproducible, disposable, scoped to non-production hardware and data, egress-allowlisted, and audit-logged — so inside it the agent can have the broad, prompt-free latitude it needs to work fast, while the worst outcome remains "rebuild the sandbox."

**The launcher (front door).** All of the above must be one step to start, or it won't get used. The launcher — a CLI (`mcuflow up`) and a thin GUI wrapper shipped together, and a standalone deliverable in its own right — hides the cage mechanics. On the developer's own desktop it: (1) brings up the cage (the pinned `espressif/idf` container on a WSL2/VM substrate, built or pulled per the lockfile); (2) mounts the project folder so `board.yml` and source are visible inside; (3) passes the connected board's USB/serial port into the cage; and (4) **starts a fresh agent session inside — or resumes the previous one** — with permissions bypassed inside and the boundary enforced at the wall (Section 7). The in-cage agent is **Claude Code by default, but the cage is agent-agnostic** — the client is a swappable setting so other agents can be slotted in. "Continue" works because the cage is disposable but the project workspace is a persistent mount, so re-entering resumes state. USB passthrough is the one OS-specific wrinkle, and the launcher owns it: on Linux a direct `--device` map; on Windows (the user's desktop) the standard `usbipd-win` bind into WSL2, which Docker then exposes to the container — automated so the user never runs it by hand. When a networked workbench (§9) is present, there is no passthrough at all: the cage reaches the board over the LAN API and needs only network access. Either way, the user runs one command.

## 7. Enforcing the boundary (defense in depth)

Section 6's freedoms are only safe if the limits are enforced *by the environment*, not by the agent's good behavior. An agent can be prompt-injected by content it fetches, and a model instructed "don't force-push" can still emit the command — so every guardrail must sit at the cage wall where the agent cannot reach it. The design rule is **the agent should be physically unable to do the forbidden thing, not merely asked not to.** Each promise from Section 6 maps to a concrete mechanism:

| Promise | Enforced by (not the agent) |
|---|---|
| Egress allowlist | Default-deny network: the container has no direct route out (`nftables`/iptables drop), and the *only* path is an allowlisting forward proxy (e.g. tinyproxy/squid/mitmproxy) that permits a fixed host set — `components.espressif.com`, `github.com`, `pypi.org`/`files.pythonhosted.org`, `mcp.espressif.com`. `HTTPS_PROXY` points there; everything else fails to connect. DNS is likewise restricted. |
| "No force-push to shared remotes" | The sandbox simply has **no credentials and no network route** to the shared remote. The agent's `origin` is a *local* mirror; promotion to the real remote is a separate, human/policy-gated CI step outside the cage. A forbidden action is impossible, not policed. |
| "No credential exfiltration" | No long-lived secrets in the image, env, or mounted filesystem. Anything privileged (registry publish, remote push) is performed by a broker *outside* the sandbox using a short-lived, narrowly-scoped token; the agent produces an artifact/branch, the broker does the privileged step. With no secrets present and no arbitrary egress, there is nothing to exfiltrate and nowhere to send it. |
| "No destructive host commands" | The container runs non-root (user namespaces), `--cap-drop ALL` with only required caps added back, never `--privileged`, under a seccomp/AppArmor profile. The host filesystem is not mounted; only the workspace is a writable bind-mount, the toolchain is read-only, and everything else is a disposable overlay. |
| Hardware access without going wide-open | Only the specific interfaces are passed through (`--device=/dev/ttyUSB0`, the matching `/dev/bus/usb` node, the JTAG probe) plus `dialout` group membership — not blanket device access. |
| Runaway containment | CPU/memory/PID `cgroup` limits and a wall-clock session timeout; a kill switch tears the unit down. |

**Untrusted-content containment.** Because the agent reads web pages, datasheets, and registry metadata, all fetched content is treated as potentially adversarial. The layers above are what neutralize an injected instruction: it cannot exfiltrate (no arbitrary egress, no secrets), cannot persist (ephemeral filesystem, rebuilt by `env up`), and cannot escalate (dropped capabilities, non-root, no host mount). Containment is what turns "the agent fetched something malicious" from an incident into a no-op.

**Audit, not trust.** Everything the agent does is logged where it cannot edit it: a command log, the proxy's access log (every egress attempt, allowed or denied), and a record of every flash operation, all written to an append-only sink outside the agent's write scope. This is for forensics and tuning the allowlists — never the primary control.

**Strength dial.** A container with the above is the default boundary and is sufficient for non-production hardware and data. If the threat model hardens (untrusted third-party components, shared infrastructure), the *same* configuration drops into a microVM (Firecracker/Kata) or a full VM for a stronger kernel boundary, with no change to the workflow above it.

## 8. HIL testing architecture

HIL is the contract, so it gets first-class infrastructure. The model that fits ESP-IDF's tooling is a **board farm behind self-hosted CI runners**:

A physical board (or several) is attached by USB to a runner machine — a **GitHub Actions self-hosted runner** (the chosen CI host; see §13). A detection step inventories what is connected and tags the runner with labels describing the attached hardware (chip type, board variant), so the CI system can route a given test job to a runner that actually has the required chip. pytest-embedded supports this directly through two marker types — `target` markers declare which chips a test supports, and `env` markers declare which runner environment it needs (e.g. `generic`, `multi_dut_generic`). Jobs are then named by the `<targets> - <env>` pattern, so `esp32s3 - generic` runs on a runner labeled accordingly.

The test pyramid: QEMU-backed pytest-embedded runs on any runner as a fast, hardware-free gate (catches logic and boot regressions cheaply); real-hardware pytest-embedded runs on the board farm as the authoritative gate; multi-DUT tests cover board-to-board interaction where the spec calls for it. Locally, a developer runs the same pytest invocation against the board on their desk — there is no separate "local vs CI" test path, which keeps results reproducible.

Reporting captures both the pytest verdict and the raw device serial/JTAG output, so a failure shows what the chip actually printed, not just an assertion error.

## 9. The networked workbench (hardware as a shared instrument)

A working reference implementation — Andreas Spiess's *Universal Embedded Workbench* — demonstrates a sharper model than "boards bolted to a CI runner," and it is the right target architecture for the physical side. Instead of the agent's machine owning the USB cable, a dedicated host becomes a **networked test instrument**: boards plug into its USB hub, and *every* interaction — flash, serial, debug, WiFi, BLE, GPIO, logs, OTA — is exposed over a single HTTP API on the LAN. The agent, the developer laptop, and CI all talk to the same instrument over the network and never need physical access. This decouples "where the agent runs" from "where the hardware lives," which is exactly what makes an autonomous, sandboxed agent practical: the sandbox reaches hardware through an API call, not a passed-through `/dev` node.

**The host must not be a Raspberry Pi specifically.** The reference runs on a Pi, but tying the instrument to one board is a limitation we explicitly design out. The instrument is a **software service** (Python + an HTTP API) plus a **hardware-capability abstraction layer**; the Pi is one host profile among many. Capabilities split into two tiers. The *portable core* — flash (esptool/RFC2217), serial, GDB/OpenOCD, UDP logging, OTA repository, MQTT broker, test API, and the dashboard — is pure software over USB and runs on essentially **any machine that runs Python and has USB**: an x86 mini-PC or NUC, an old laptop, a NAS or Docker host, another SBC (Orange Pi, Radxa/Rock, BeagleBone, Le Potato), or even the developer's own workstation with no separate box at all. The *radio/GPIO instruments* — WiFi AP/STA, BLE, GPIO stimulus, signal generator — are the only parts that need specific hardware, and each is a **pluggable backend** rather than a hard dependency:

| Instrument | Default backend (any host) | Fallback backends |
|---|---|---|
| WiFi AP/STA | **ESP32 satellite** over USB | onboard `wlan0` + hostapd/dnsmasq (Pi/Linux); USB WiFi adapter (AP-capable) |
| BLE | **ESP32 satellite** over USB | onboard Bluetooth + BlueZ; USB Bluetooth dongle |
| GPIO stimulus (reset/boot, button) | **ESP32 satellite** GPIO over USB | Pi header via `/dev/mem`; USB-GPIO adapter (FT232H, MCP2221, USB relay board) |
| Signal generator | **ESP32 satellite** output (where adequate) | Si5351/PE4302 via I²C/GPIO or a USB-I²C bridge (FT232H/MCP2221); any USB-attached siggen |

The service **discovers and advertises its capabilities** at startup (`GET /api/capabilities`), and tests declare what they need — the same marker/routing idea already used for chips in Section 8 extends to instruments, so a suite needing BLE is routed to a host that has a BLE backend and skips cleanly where it doesn't. The result: the *full* instrument runs on a Pi or any Linux box with the right dongles; a *core* instrument (flash/serial/debug/logging/OTA/test) runs anywhere, including the developer's laptop; and missing capabilities degrade to skipped tests, never hard failures.

**The ESP32 satellite is the chosen default for radio/GPIO.** Rather than depend on the host's onboard radios or a grab-bag of OS-specific USB dongles, the standard portable backend is a dedicated **ESP32 "satellite"** — a second, cheap ESP32 running a fixed companion firmware that the instrument drives over USB-serial (or its own network link) to provide WiFi AP/STA, BLE, GPIO stimulus, and even signal-style output. This is deliberately chosen as the default because it makes the *entire* instrument truly host-agnostic with one inexpensive, identical part: the host needs only Python and a USB port, and the radios behave identically whether the host is a Pi, a mini-PC, a NAS, or a Windows/macOS laptop where native AP/BLE control is otherwise awkward or impossible. It also keeps the test radios on the same silicon family as the DUT, which is representative for ESP-to-ESP scenarios. The satellite's companion firmware is therefore a first-class deliverable of this project (built and flashed by the very workflow it serves), with onboard-radio and USB-dongle backends kept as fallbacks for hosts that already have suitable hardware.

Several capabilities this model adds were missing from the earlier sketch, and each is worth absorbing:

**Zero-config slot model.** On boot the instrument walks the USB hub topology and creates one slot per physical port. Plug in any board and it auto-maps to a slot, gets chip identification, a network serial endpoint (RFC2217, so binaries stay on the client and flashing happens over TCP), and an auto-started OpenOCD/GDB port. No per-board configuration. This is the discovery step from Section 5, but realized as an always-on instrument rather than a CI bootstrap script.

**Wireless and protocol instruments — the big gap.** Testing a connected device means exercising its radios and protocols, not just its logic. The workbench turns its radio backends (onboard, a USB dongle, or an ESP32 satellite — see the host-agnostic note above) into test gear: a programmable **WiFi** AP/STA (to drive provisioning, captive-portal, and join flows), a **BLE** scan/connect/write proxy (to exercise GATT services), an **MQTT** broker plus test traffic (for IoT messaging), and an **HTTP relay** onto the test network. Our plan previously tested firmware that *runs*; this tests firmware that *communicates*.

**Out-of-band logging.** A **UDP log receiver** collects device logs over the network — essential when the USB port is unavailable because the device is acting as a USB HID keyboard, a mass-storage gadget, or is mid-OTA. Serial-only log capture silently fails for exactly those cases.

**Stimulus and recovery via GPIO.** The host drives wires to the DUT's EN/RST and BOOT pins to force download mode, trigger factory reset, or enter a captive-portal boot — and to **auto-recover a bricked/bootlooping board** (detect USB flapping, unbind, drop into download mode) without a human. This is a stronger version of the "power-cycle to recover" idea: the instrument can un-brick a board mid-run.

**OTA repository.** The instrument serves firmware binaries over HTTP so the DUT can pull an `esp_https_ota` update from the local network — closing the loop on the single most failure-prone field operation, OTA, as a routine test.

**Human-in-the-loop.** A test script can block on a "please press the button / connect the jumper" modal and resume when an operator confirms. Full autonomy is the goal, but acknowledging that some HIL steps need hands — and making that a first-class, awaitable API call rather than a dead end — is what keeps a suite runnable end-to-end.

**Live dashboard.** A web portal shows every slot's state (running/idle/absent/recovering/download-mode), detected chip, debug status, activity log, and live test progress — the operator's single pane of glass.

**(Specialized) signal generator.** For RF work the reference adds a programmable carrier (Si5351/GPCLK) with a step attenuator and Morse keying — an optional stimulus instrument. Niche, but it illustrates the pattern: any bench instrument can hang off the same API.

The integration consequence for our design: the `Flasher`/`TestRunner` interface from Section 4 gains a **networked backend** alongside the local-USB one, selected automatically ("use the workbench if reachable, else local USB"). The CLI and skill talk to the workbench's HTTP API; the WiFi/BLE/MQTT/UDP-log/OTA/GPIO operations become new verbs and new test fixtures. Crucially, this is the cleanest possible hardware story for the sandboxed agent of Sections 6–7: the agent needs only *network* access to the instrument's API (one more allowlisted host), not raw USB/device passthrough, so the blast radius shrinks further while the capability set grows.

## 10. Proposed artifact: a three-layer bundle

**Layer 1 — Project template.** A cookiecutter-style ESP-IDF project that is correct on day one: `board.yml`, `CMakeLists.txt`, `sdkconfig.defaults`, `idf_component.yml`, a `main/` with peripheral init stubs, a `pytest_app.py` HIL skeleton, and a CI workflow wired for self-hosted board runners. Valuable even used by hand.

**Layer 0 — Satellite firmware.** The ESP32-satellite companion firmware (Section 9) is a shipped artifact in its own right: a fixed, flashable image exposing WiFi/BLE/GPIO/signal backends over USB-serial so any host gains radio/GPIO instruments from one cheap board. It is built and flashed by the same workflow it serves — the project's first dogfooding case.

**Layer 2 — CLI / library (`mcuflow`).** A thin tool exposing the six stages as deterministic verbs (`mcuflow spec`, `scaffold`, `build`, `flash`, `test`, `report`) over a target-agnostic core (`Board`, `Toolchain`, `Flasher`, `TestRunner`) with an ESP32 adapter that shells out to `idf.py`/`esptool`/pytest-embedded. It is **defined by its contract, not its language**: every command emits structured JSON with documented exit codes so it composes identically in scripts, CI, and agent tool-calls, and the implementation language stays an internal, swappable detail (Python is the natural starting point; a Go/Rust build can replace or wrap it later without affecting any caller).

**Layer 3 — Skills (the orchestration brain).** Rather than one monolithic skill, follow the reference implementation's pattern of **one focused skill per capability** — build/flash lifecycle (ESP-IDF *and* PlatformIO), test harness, debug, WiFi, BLE, MQTT, serial/UDP logging, OTA integration, signal generator, plus an `fsd-writer` (spec generation) and an `integration` skill (one-shot wiring of a project to the workbench) — coordinated by a thin top-level orchestration skill. Each skill teaches the agent how to drive one slice of the workbench API or toolchain; the orchestrator reads `board.yml`/the FSD, sequences them, and wires in the two Espressif MCP servers (Docs to ground hardware decisions, Tools to execute build/flash/status). The agent's value is judgment and recovery: interpreting a build error against the docs, picking pins, deciding whether a HIL failure is a flake (re-run) or real (report), un-bricking a board via GPIO, and narrating the loop end-to-end. Skills auto-detect whether hardware is on a networked workbench or local USB and adapt.

These layers degrade gracefully: the template works with no skill, the CLI works with no agent, the skills add reasoning on top of both — and an individual skill (e.g. `fsd-writer`, `signal-generator`) is useful even with no workbench present.

**Who orchestrates.** Two distinct conductors, per the fifth/sixth design principles. Layer 2 (the CLI) is the **deterministic conductor**: it runs the fixed pipeline in order, reproducibly, headless, with no model — this is what CI and scripted runs use. Layer 3 (Claude + the skills) is the **judgment orchestrator**: it sits above the pipeline, calls the same verbs, and reasons about which to run, in what order, and how to recover when one fails — delegating to per-domain subagents (design, firmware, test) where useful. Claude is therefore the orchestrator for *intelligence*, never the load-bearing sequencer for *mechanics*; the system still runs end-to-end when no model is present, with Claude adding judgment on top rather than being a single point of failure.

### Deliverables inventory (modular components)

The project is deliberately many small, independently-shippable pieces rather than one tool. Each has a clear contract, is useful on its own where possible, and composes with the rest via the conductor. This inventory is the running map of what gets built.

| # | Deliverable | What it is | Depends on | Phase | Useful alone? |
|---|---|---|---|---|---|
| 1 | **`board.yml` schema + validator** | The single-source-of-truth contract and its checker | — (foundational) | 1 | yes |
| 2 | **CLI / library (`mcuflow`)** | Canonical deterministic conductor; the pipeline verbs (spec/scaffold/build/flash/test/report + env) | idf.py, esptool, pytest-embedded; #1 | 1 | yes |
| 3 | **Project template** | Cookiecutter ESP-IDF project, correct day one | #1 | 1 | yes |
| 4 | **Launcher (`mcuflow up` CLI + thin GUI)** | Front door: opens the cage, USB passthrough (usbipd→WSL2), seats the agent (Claude Code default, agent-agnostic) | container runtime/WSL2; #2 | 1 | yes |
| 5 | **Cage definition + boundary enforcement** | Container image, egress-allowlist proxy, seccomp/cap-drop, audit sink | container runtime | 3 | partially |
| 6 | **Stage 0 design assistant** | Requirements → board/module selection → buyable BOM w/ live links → wiring guide → power budget → (KiCad only when needed) | web search, Docs MCP; #1 | 0 | yes |
| 7 | **Enclosure generator** | Parametric build123d → STL/3MF from `enclosure:` | build123d, OCP CAD Viewer; #1 | 0 | yes |
| 8 | **ESP32 satellite firmware (Layer 0)** | Companion image: WiFi/BLE/GPIO/signal over USB-serial | the workflow itself (dogfood) | 5 | yes |
| 9 | **Workbench service** | Host-agnostic HTTP/RFC2217 instrument (serial, GDB, WiFi, BLE, MQTT, GPIO, UDP-log, OTA) | esptool, OpenOCD, pytest-embedded driver; #8 or dongles | 4 | yes |
| 10 | **Skills (per capability)** | build/flash (IDF+PIO), HIL test, debug, WiFi, BLE, MQTT, logging, OTA, signal-gen, `fsd-writer`, enclosure, integration, + top-level orchestrator | #2 / #9 APIs; Docs+Tools MCP | 3+ | each yes |
| 11 | **CI pipeline templates** | GitHub Actions self-hosted; runner-label routing by chip/instrument | #2; runner setup | 2 | yes |
| 12 | **Platform adapters** | STM32 / RP2040 / Zephyr behind the same core interface | #2 core | 6 | yes |

*Built since this plan was drafted (same contracts, no new design):* a few small
standalone verbs that fell out of real bring-up — `mcuflow ports` (a
side-effect-free viewer of which board is on which COM port, by USB serial),
`mcuflow bridge` (RFC2217 serial-over-network, deliverable #9's serial-proxy
layer), and `mcuflow debug` (the OpenOCD/GDB server, the JTAG layer) — plus a
**VS Code extension** (`editors/vscode/`) that surfaces the CLI verbs as a
PlatformIO-style GUI (Home page, project recognition by `board.yml`, activity-bar
view). The extension reimplements nothing: the CLI stays the single source of
truth, exactly as the "who orchestrates" split requires.

## 11. Extensibility beyond ESP32

The target-agnostic core is the hinge. `board.yml` keeps a `platform:` field; the CLI dispatches to a platform adapter implementing the same `Toolchain`/`Flasher`/`TestRunner` interface. ESP32's adapter wraps `idf.py`; a future STM32 adapter wraps CMake + `arm-none-eabi-gcc` + OpenOCD; an RP2040 adapter wraps the Pico SDK + `picotool`; a Zephyr adapter wraps `west` + Twister (whose HIL model closely mirrors pytest-embedded's marker/runner approach). pytest-embedded itself is not ESP-exclusive, which keeps the test layer portable. The skill and template are parameterized by platform, so most of the per-platform cost is the adapter plus a template variant.

## 12. Phased roadmap

Phase 0 (design assistant): the Stage 0 flow — requirements → prebuilt-board/module selection → buyable BOM with links → wiring guide → power budget — plus the build123d enclosure generator. These are independent of the firmware loop and immediately useful to a novice, so they can ship first. Phase 1 (ESP32 happy path): the project template, `mcuflow env up` for one-command virtual-environment provisioning (pinned EIM/ESP-IDF + venv), the **launcher (`mcuflow up` CLI plus a thin GUI)** that opens the containerized cage, passes the USB board through (usbipd→WSL2 on Windows), and seats the agent inside (Claude Code by default, agent-agnostic), and a `build`/`flash`/`monitor` wrapper that produces structured output; manual `board.yml`. Phase 2 (testing): pytest-embedded HIL skeleton, QEMU gate, and a single self-hosted runner with board detection. Phase 3 (the skill + autonomous agent): integrate both Espressif MCP servers, ship the orchestration skill, and stand up the sandboxed agent-ready environment (containerized, permission-bypassed inside the cage, hardware interfaces passed through) so an agent can run the loop unattended; add spec-to-scaffold generation driven by the Docs server. Phase 4 (the networked workbench): stand up the host-agnostic instrument (§9) on whatever host is handy — Pi, mini-PC, or the dev laptop — with the portable core (HTTP/RFC2217 serial, auto-started GDB, zero-config slots) plus a capability-advertisement endpoint, and add the networked backend to the `Flasher`/`TestRunner` interface. Phase 5 (wireless & protocol testing): build and flash the **ESP32 satellite firmware** (Layer 0) as the default radio/GPIO backend, then the WiFi/BLE/MQTT/UDP-log/OTA instruments and their test fixtures and skills on top of it, plus GPIO stimulus and auto-recovery; onboard/dongle backends added as fallbacks. Phase 6 (scale & generalize): multi-DUT and board-farm CI, human-in-the-loop and the live dashboard, then the second platform adapter to prove the abstraction. Each phase ends with a working, demoable loop.

## 13. Open decisions

The pre–Phase 1 decisions are now resolved; the items below record what was decided and why.

*Resolved:* the **CLI is the single canonical execution path** for the whole pipeline (build, flash, test, env, enclosure, instruments) — CI, scripts, and the agent all go through it for identical behavior. Espressif's **Docs MCP server is adopted** to ground the agent's hardware/API decisions; its **Tools MCP server is optional/complementary** (a convenience for ad-hoc agent build/flash), not the foundation, because it is agent-only (no headless/CI path), covers only a slice (build/flash/clean/target), and a second path to `idf.py` would risk drift. If the agent later needs first-class build/flash as tool-calls, the move is to wrap our own CLI in a thin MCP shim so there is still exactly one behavior underneath.

*Resolved:* the environment defaults to the **containerized "cage"** even on the developer's own desktop (not native), opened by a one-step launcher (`mcuflow up` / GUI) that brings up the container, mounts the project, passes the USB board through (via `usbipd`→WSL2 on Windows), and starts or resumes the agent inside — bypassed-permissions-inside, enforced-boundary (Sections 6–7). A native install stays available as a manual escape hatch; a networked workbench removes USB passthrough entirely when used.

*Resolved:* the `board.yml` schema is locked as the **single source of truth** (see Section 3, "The board.yml contract") — one sectioned file with optional sections, from which scaffold, build, flash, test routing, enclosure, and wiring are all derived.

*Resolved:* CI host is **GitHub Actions with self-hosted runners** (the user hosts on GitHub). Self-hosted is required regardless of platform because the HIL stage needs physically attached hardware; GitHub's runner labels map directly onto the chip/instrument tags from Section 8. Because the pipeline lives in the contract-first CLI, the CI config stays a thin "check out → `mcuflow env up` → build/flash/test → upload report," so the choice is low-lock-in.

*Resolved:* the CLI is **implementation-agnostic** — it is defined by its *contract* (a stable set of verbs with JSON in/out and documented exit codes), not its language. The implementation language is therefore an internal, swappable detail: it can start in Python (closest to `idf.py` and pytest-embedded) and be re-implemented or wrapped in Go/Rust for distribution later, with no change to callers. Anything that consumes the CLI — scripts, CI, the skills, an agent's tool-calls — binds to the contract, so the language choice never leaks into the rest of the system.

*Resolved:* the portable radio/GPIO backend standardizes on the **ESP32 satellite** (Section 9), with onboard-radio and USB-dongle backends as fallbacks. The satellite's host link is **USB-serial** — simplest, always available, and self-contained on the bench. The command protocol is kept transport-agnostic so a networked link can be added later for remote placement (range/roaming tests, RF chamber) without redesigning the satellite API; USB-serial remains the default.

## 14. Sources

- [ESP-IDF Releases (GitHub)](https://github.com/espressif/esp-idf/releases) · [Announcing ESP-IDF v6.0](https://developer.espressif.com/blog/2026/03/idf-v6-0-release/) · [ESP-IDF Versions](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/versions.html)
- [ESP-IDF Tools Local MCP Server](https://developer.espressif.com/blog/2026/04/esp-idf-tools-mcp-server/) · [Espressif Documentation MCP Server](https://developer.espressif.com/blog/2026/04/doc-mcp-server/)
- [ESP-IDF Installation Manager v0.8](https://developer.espressif.com/blog/2026/03/esp-idf-installation-manager/)
- [IDF Component Manager](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-guides/tools/idf-component-manager.html)
- [ESP-IDF Tests with Pytest (HIL guide)](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/contribute/esp-idf-tests-with-pytest.html)
- [Automatically Detecting Boards for HIL Testing (Golioth)](https://blog.golioth.io/automatically-detecting-boards-for-hardware-in-the-loop-hil-testing/) · [Automated hardware testing using pytest (Golioth)](https://blog.golioth.io/automated-hardware-testing-using-pytest/)
- [AI-Driven ESP32 Workflow (Spec → Code → Test) using Claude Code — Andreas Spiess (video)](https://www.youtube.com/watch?v=nmGEedloQ6E) · [Universal Embedded Workbench (reference implementation, GitHub)](https://github.com/SensorsIot/Universal-Embedded-Workbench)
- [build123d (code-CAD library)](https://build123d.readthedocs.io/) + the OCP CAD Viewer VS Code extension (live preview); KiCad with JLCPCB/PCBWay for custom-PCB fabrication
