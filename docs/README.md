# Documentation

Human-facing docs for mcu-workflow. (Material written for AI coding agents lives
under [`../agents/`](../agents/).)

## Start here

- **[Project README](../README.md)** — what this is, install, and the quick start.
- **[architecture.md](architecture.md)** — the full design: the `board.yml`
  contract, the deterministic CLI conductor, the cage and its boundary, the
  satellite/workbench test rig, and how the pieces fit.
- **[runbook-c3.md](runbook-c3.md)** — step-by-step bring-up of two ESP32-C3
  Super Minis, end to end. Runs in simulation today; one flag flips to real boards.

## Per-module references

Each module under [`../src/`](../src/) (and the Stage-0 helpers under
[`../hardware/`](../hardware/)) ships its own `README.md`:

| Module | Path |
|---|---|
| CLI conductor | [`../src/mcuflow/`](../src/mcuflow/) |
| board.yml schema + validator | [`../src/board-schema/`](../src/board-schema/) |
| project scaffold | [`../src/project-template/`](../src/project-template/) |
| cage launcher | [`../src/launcher/`](../src/launcher/) |
| networked workbench | [`../src/workbench/`](../src/workbench/) |
| ESP32 satellite | [`../src/satellite/`](../src/satellite/) |
| simulators + HIL | [`../src/sim/`](../src/sim/) |
| platform adapters | [`../src/adapters/`](../src/adapters/) |
| Stage-0 design / enclosure | [`../hardware/`](../hardware/) |
| cage egress proxy | [`../deploy/cage/`](../deploy/cage/) |
| CI templates (copy into your project) | [`../ci-templates/`](../ci-templates/) |
