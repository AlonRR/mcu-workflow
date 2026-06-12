# skills — capability skills (deliverable #10)

One focused skill per slice of the workflow, coordinated by a top-level orchestrator. This is the *judgment* layer (`ARCHITECTURE.md` "Who orchestrates"): each skill teaches the agent how to drive one part via the `mcuflow` CLI or the workbench API — the deterministic mechanics live in those tools, not in the skills.

## Shipped here

| Skill | Drives |
|-------|--------|
| `orchestrator` | top-level loop: read `board.yml`/FSD, sequence verbs, delegate, recover |
| `build-flash` | `mcuflow build` / `flash` / `monitor` (ESP-IDF + PlatformIO) |
| `hil-test` | pytest-embedded via `mcuflow test`; flake-vs-real judgment |
| `workbench-instruments` | WiFi / BLE / MQTT / UDP-log / OTA / GPIO over the workbench API |

Plus, from their own deliverables: `mcu-design-assistant` (#6) and the `fsd-writer` pattern.

## Still to split out (same pattern)

The reference workbench breaks `workbench-instruments` into finer skills (`workbench-wifi`, `workbench-ble`, `workbench-mqtt`, `workbench-logging`, `workbench-debug`, `signal-generator`, `workbench-integration`). They follow the identical "read capabilities → call the API → report what was observed" shape and can be peeled off as needed.

## Install

These are project skills. Copy a skill's folder into `.claude/skills/` in your project (or `~/.claude/skills/` for all projects), then restart the agent session so it loads them — the same convention as the reference Universal Embedded Workbench.

## Principle

Skills never call each other directly; the orchestrator (or the deterministic conductor) wires them via the tools' contracts. That keeps each skill independently shippable.
