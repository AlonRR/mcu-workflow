# skills — capability skills

One focused skill per slice of the workflow, coordinated by a top-level
orchestrator. This is the *judgment* layer (`docs/architecture.md` "Who
orchestrates"): each skill teaches the agent how to drive one part via the
`mcuflow` CLI or the workbench API — the deterministic mechanics live in those
tools, not in the skills.

## Shipped here

| Skill | Drives |
|-------|--------|
| `orchestrator` | top-level loop: read `board.yml`/FSD, sequence verbs, delegate, recover |
| `build-flash` | `mcuflow build` / `flash` / `monitor` (ESP-IDF; native or the Docker cage) |
| `hil-test` | pytest-embedded via `mcuflow test`; flake-vs-real judgment |
| `workbench-instruments` | WiFi (AP/scan) + GPIO + the ESP32 satellite over the workbench HTTP API |

A related skill lives next to the code it describes:
[`hardware/design/SKILL.md`](../../hardware/design/SKILL.md) (`mcu-design-assistant`).

## Planned (not yet implemented)

These are part of the workbench vision but are **not** in the current API, so the
skills above deliberately don't reference them — an agent should check
`GET /api/capabilities` and skip what's absent. As each lands in
`src/workbench/`, give it the same "read capabilities → call the API → report
what was observed" shape (optionally as its own finer skill): BLE
(`workbench-ble`), MQTT (`workbench-mqtt`), UDP logging (`workbench-logging`),
OTA, JTAG/debug (`workbench-debug`), a signal generator, and RFC2217 flashing
over the network.

## Install

These are project skills. Copy a skill's folder into `.claude/skills/` in your
project (or `~/.claude/skills/` for all projects), then restart the agent session
so it loads them.

## Principle

Skills never call each other directly; the orchestrator (or the deterministic
conductor) wires them via the tools' contracts. That keeps each skill
independently shippable — and a skill describes only what works **today**:
planned capability goes in the list above, never in a skill body or its
`description` (a `description` is the trigger, so advertising an unbuilt
capability makes the skill fire and then fail).
