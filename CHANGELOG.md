# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-07-24

### Added
- `mcuflow mcp`: an MCP server (architecture §12.1) that exposes the CLI verbs
  (`validate scaffold build flash monitor test hil run doctor ports` + `env
  doctor`) as tool-calls over stdio. It is a transport, not a reimplementation —
  every tool shells out to `mcuflow <verb> --json`, and the tool input-schemas
  are derived from the CLI's own argparse parser, so the two can't drift. Needs
  the optional `mcp` extra (`uv pip install -e ".[mcp]"`); the base CLI stays
  dependency-light. See [docs/mcp-server.md](docs/mcp-server.md).
- `mcuflow monitor --seconds N [--until STR]`: a bounded, non-interactive serial
  capture that emits the transcript as a JSON envelope (what the MCP `monitor`
  tool and CI use), alongside the existing interactive session.
- One-line bootstrap installers (`install.sh`, `install.ps1`): install uv, a
  Python, the repo, and all prerequisites, and put `mcuflow` on PATH — nothing
  needs to pre-exist.
- `pyproject.toml`: standard installable layout, a `mcuflow` console script, and
  dependencies as the single source of truth.
- `mcuflow doctor --fix` self-install and `doctor --uninstall` / `--purge`
  teardown.
- Cage build + host `esptool` flash, so no native ESP-IDF install is needed.
- On-silicon HIL: `run`/`hil` read the real DUT serial to confirm boot + WiFi join.
- `ruff` lint gate and CI (smoke + lint).
- `mcuflow ports`: a viewer (stdlib tkinter, `--watch`/`--list`) that shows which
  board is on which COM port — serial numbers, suggested DUT/satellite roles with
  a reason, and the commands the mapping implies. Read-only; it never touches a
  board.
- `mcuflow run` (real hardware, no `--port`) auto-detects the DUT port from the
  connected boards and narrates the choice as a visible "ports" stage (with the
  satellite noted), so the automatic assignment is never silent.
- `mcuflow bridge`: share a serial port over the network (RFC2217, via esptool's
  server) so a board on one host can be flashed/monitored from another with
  `--port rfc2217://<host>:<tcp>`.
- Workbench signal generator: `/api/siggen/start|stop` drive a PWM (LEDC) on a
  satellite pin (firmware `siggen.start/stop`).
- Workbench UDP logging: `/api/udplog` collects device log lines a board ships
  over UDP (for when its USB serial is busy); `--udp-port` sets the listen port.
- Workbench OTA serving: `POST /api/firmware/upload` (base64), `GET /api/firmware`,
  and `GET /firmware/<name>` so a DUT can pull an update over HTTP; `--firmware-dir`
  sets the store.
- Embedded MQTT broker (stdlib, QoS 0) on TCP 1883 (`--mqtt-port`), with
  `/api/mqtt/publish` and `/api/mqtt/recent` - no mosquitto needed.
- BLE scan (`/api/ble/scan`): NimBLE observer on the satellite + workbench
  endpoint + host driver + simulator. Software path and sim are verified; the
  on-silicon scan currently resets the C3 (experimental, pending on-device
  debugging - the panic isn't capturable over the USB-JTAG console headlessly).
- `mcuflow debug`: start an OpenOCD GDB server (`:3333`) over the chip's built-in
  USB-JTAG for step-debugging (needs OpenOCD; Windows needs a Zadig WinUSB
  driver).
- VS Code extension (`editors/vscode/`): a GUI for the `mcuflow` CLI — Home page,
  New Project (folder + name, then a Configure step for platform/chip/devices/
  tests), `board.yml` project recognition, activity-bar view (Boards / Project /
  Tools / Doctor), status bar, and command palette. Inspired by PlatformIO IDE;
  an independent implementation that contains no PlatformIO code.
- `tools/satcheck.py`: one-shot satellite check (ping / caps / siggen / ble, or
  `--sim` with no hardware) that starts the workbench in-process and exits.
- `LICENSE`: the project is now released under the Mozilla Public License 2.0,
  declared in `pyproject.toml` and the VS Code extension manifest.

### Changed
- CI now uses **uv** instead of pip: both workflows install via
  `astral-sh/setup-uv` + `uv pip install`, and lint runs `uvx ruff`.
- Reorganized the repository into `src/`, `docs/`, `agents/`, `hardware/`,
  `deploy/`, with examples at the top level.
- The CLI no longer assumes ESP at the command layer: `build`/`flash`/`monitor`/
  `run` go through the platform adapter (`get_adapter(meta.platform)`), and
  `scaffold` dispatches by platform. ESP-IDF remains the only implementation, but
  adding a platform is now a contained adapter + generator (no CLI changes).
- The cage image + cage-build + host-flash now live on the platform adapter
  (`cage_image`/`toolchain_tools`/`cage_build_cmd`/`host_flash_cmd`), so each
  platform owns its toolchain and `doctor` asks the adapter what to provision.
- The launcher requires the in-cage agent to be defined before entry (cage.yaml
  `agent:` or `--agent`); no implicit Claude default.
- Workbench default port moved off the collision-prone `8080` to `6283`.
- VS Code extension: `doctor`/`ports` reads are briefly cached (1.5 s), so a
  single activation or refresh no longer spawns the CLI several times over (the
  tree and Home page previously each ran both); an explicit Refresh clears it.

### Fixed
- Launcher arguments: a flat parser now accepts global flags on either side of
  the subcommand, so the documented `--project . up --busid <id> --dry-run`
  (globals on both sides) parses.
- `mcuflow --sim up …` / `--json up …` now forward to the launcher; a leading
  global no longer drops the passthrough option (argparse REMAINDER quirk).
- `up --dry-run` prints the full, auditable plan without requiring an in-cage
  agent (real entry still refuses to start without one).
- `up doctor` no longer mistakes a down Docker daemon's error text for an image
  id (false "present"); it reports the daemon as unreachable and the readiness
  line says to start Docker rather than "yes".
- Launcher rejects a single-subcommand flag on the wrong subcommand (e.g.
  `mcuflow up --fix`, a typo for `up doctor --fix`, no longer silently starts a
  cage), and warns that `--busid`/`--device` are ignored when resuming a cage.
- The up/workbench passthrough skip-set is derived from the parser, so adding a
  global flag can't silently re-break leading-global forwarding.
- `run` surfaces a real port-detection failure as a failed stage instead of
  masking it as "no board" and flashing the toolchain default; `doctor` and
  `mcuflow ports` now report the same connected-board list.
- `tools/satcheck.py` resolved the workbench relative to its own `tools/`
  directory after the move to a standard layout, so every invocation crashed at
  import; it now resolves the repo root correctly.
- CI smoke job runs `uv run --extra dev pytest` instead of a bare `pytest`,
  which need not resolve under the uv-managed interpreter (matches the lint
  workflow's uv usage).
- VS Code extension: the Test and HIL actions invoked the CLI without the
  required positional argument (an argparse usage error every time); they now
  pass the board file.
- VS Code extension: Configure offered ESP-only chips for every platform (e.g.
  `esp32c3` for an `stm32` project); chips are now platform-aware, with free text
  for platforms without a curated list, and device drivers (e.g.
  `espressif/bme280`) are emitted per platform instead of for all.
- VS Code extension: "Refine with Agent" no longer targets an unrelated `.yml`
  that happens to be focused; Debug defaults the chip from `board.yml` instead of
  hardcoding `esp32c3`; and terminal arguments are quoted correctly for
  PowerShell (the Windows default integrated terminal).
- Workbench: `/api/udplog` and `/api/mqtt/recent` snapshot their deques under a
  lock — iterating while the UDP-listener/MQTT threads append raised
  intermittent `RuntimeError("deque mutated during iteration")` exactly when
  log traffic was heaviest.
- sim HIL no longer fails every non-WiFi project: the AP/join steps are gated
  on `wifi` in `test.needs` (case-insensitively, since `board.yml` is loaded
  here with no schema check; a serial-only board passes on its boot gate), a
  failed `ap_start` skips the join instead of waiting out its timeout, and the
  AP teardown in `finally` is attempted whenever wifi was wanted at all rather
  than gated on a successfully-*read* `ap_start` reply — a satellite can raise
  the AP and then have the response to that call time out, which would
  otherwise skip teardown and leave the test AP broadcasting.
- The HIL HTTP helper treats every workbench-call failure — non-2xx replies
  (e.g. 503 "no satellite backend") *and* connectivity failures (unreachable
  host, timeout, connection refused) — as a normal failed result instead of a
  raised exception, so `hil` always produces its structured per-step report
  instead of crashing.
- `mcuflow` now prepends the `.venv` Scripts/bin dir to `PATH` at startup, so
  tool checks and invocations (e.g. `test`'s pytest) resolve exactly like
  `doctor` reports them — `doctor --fix` followed by `mcuflow test` works
  instead of exiting 127 against a green doctor.
- `doctor`'s port listing never crashes: a missing sibling module
  (non-editable install) or a failing enumerator degrades to "no ports"
  instead of a traceback — doctor is what users run when things are broken.
- Launcher: the "docker not found" guard now applies on Windows too, replacing
  a raw `FileNotFoundError` traceback with the friendly exit-127 message.
- Arduino satellite edition: the unknown-command reply no longer serializes a
  dangling pointer (ArduinoJson stores `const char*` by reference; the String
  is now copied); `caps` only advertises what the edition implements (BLE
  removed — it's an IDF-edition stub here); and `siggen.start/stop` are
  implemented via LEDC for protocol parity with the IDF edition (core 3.x API).
- VS Code extension: terminal arguments are single-quoted (fully literal) on
  PowerShell and POSIX shells — the double-quote form left `` ` `` and `$`
  live, so bash/zsh executed the backtick-wrapped `mcuflow validate` inside
  the Refine prompt via command substitution before the agent ever saw it.
  cmd.exe (which doesn't treat `'` as a quote character at all) is now
  detected via `vscode.env.shell` and gets its own double-quote form; the
  "safe to leave unquoted" allowlist no longer includes `@`, which PowerShell
  parses as the splat operator in leading position.
- VS Code extension: New Project rejects names consisting only of dots — `..`
  passed the character whitelist and `path.join(location, "..")` would write
  the project (and silently overwrite `.vscode/settings.json`) into the
  *parent* of the chosen folder.
- VS Code extension: `Test (HIL)` no longer passes `board.yml` to `pytest`
  when `mcuflow.simulate` is off (the default) — the CLI's `test` positional
  is only a board.yml under `--sim`; without it, it prompts for an actual
  pytest file.
- VS Code extension: `Refine with Agent`'s auto-detect matches the *configured*
  board file (`mcuflow.boardFile`, e.g. `examples/board-c3.yml`) as well as a
  literal `board.yml`, in both the active-editor check and the workspace-root
  fallback — it had narrowed to an exact `board.yml` match only, missing every
  project using the extension's own non-default default.
- VS Code extension: the port picker (`pickPort`/`bridge`) forces a fresh
  `ports` read instead of reusing the 1.5 s cache the tree/Home views may have
  just populated, so a board plugged in immediately beforehand isn't missing
  from the list.
- Fixed two literal NUL bytes that had corrupted `cli.ts`'s cache-key line
  (`${r.cwd}\0${r.exec.file}...`), which made grep/file-type tools treat the
  whole file as binary.

### Security
- The workbench binds `127.0.0.1` by default (was `0.0.0.0`): the HTTP API can
  drive GPIO/WiFi and accept OTA firmware uploads, so LAN exposure is now an
  explicit choice (`--host 0.0.0.0`), warned about when made without a token.
  The startup banner always states whether the bind is local-only or
  LAN-reachable (and token-gated or not) — a caller who relied on the old
  0.0.0.0 default and passes no `--host` at all now gets a visible signal
  instead of a silent behavior change.
- New `--token` / `WORKBENCH_TOKEN` shared secret: when set, every endpoint
  except `/api/health` requires `Authorization: Bearer <token>` (constant-time
  compare); the HIL harness sends it automatically from the environment.
- POST bodies are capped at 32 MiB (413 beyond that) — `Content-Length` was
  previously read into RAM unbounded.
- VS Code extension: `Start Workbench` gained `mcuflow.workbench.host` /
  `mcuflow.workbench.token` settings (both default empty, so the CLI's
  loopback-only default applies unchanged) and warns in the UI when a
  non-loopback host is set with no token — the command previously always
  launched with no flags, silently inheriting whatever the CLI defaulted to.

## [0.2.0]

- First end-to-end run on real two-ESP32-C3 hardware: validate → scaffold →
  build → flash → workbench-mediated HIL, all green.
- ESP-IDF v6.0 fixes (managed `espressif/cjson`, split `esp_driver_*`
  components) and a boot-noise-tolerant satellite host driver.
