# mcuflow — the conductor CLI (deliverable #2)

`mcuflow` is the single canonical entry point for the workflow — the *deterministic conductor*. It wraps the modular deliverables as verbs with a stable contract: human output by default, one JSON object with `--json`, and documented exit codes. CI, scripts, and the agent all go through it, so behavior never diverges (see `docs/architecture.md`, "Who orchestrates").

## Use

After install (see the root README — no pre-existing Python needed), `mcuflow`
is on PATH and runs under the project's uv `.venv`. From the repo root:

```bash
mcuflow validate examples/board-c3.yml
mcuflow scaffold examples/board-c3.yml -o ./my-project
mcuflow doctor
mcuflow --json validate examples/board-c3.yml      # machine-readable
```

## Verbs

| Verb | Does | Backed by |
|------|------|-----------|
| `validate <board.yml>` | structure + semantic check | deliverable #1 |
| `scaffold <board.yml> [-o dir]` | generate an ESP-IDF project | deliverable #3 |
| `build [--path .]` | build via the platform adapter (or the Docker cage, or `--sim`) | adapter / ESP-IDF |
| `flash [--path .] [--port P]` | flash via the adapter (or host `esptool`, or `--sim`) | adapter / esptool |
| `monitor [--path .] [--port P]` | serial monitor via the adapter (interactive) | adapter / ESP-IDF |
| `test <pyfile> [--target chip]` | pytest-embedded HIL run (or `--sim`) | pytest-embedded |
| `hil <board.yml>` | workbench-mediated HIL (sim or real) | deliverable #9 |
| `run <board.yml>` | validate → scaffold → build → flash → hil | the verbs above |
| `up` | open the cage / pass USB through | deliverable #4 |
| `workbench` | run the networked test instrument | deliverable #9 |
| `ports` | view connected boards / COM-port mapping (GUI) | deliverable (portviewer) |
| `bridge` | serve a serial port over the network (RFC2217) | deliverable (serialbridge) |
| `debug` | start an OpenOCD GDB server (built-in USB-JTAG) | deliverable (debugger) |
| `doctor` | preflight: deps, toolchain, ports, satellite (`--fix` self-installs) | — |
| `env doctor` | report toolchain availability | — |

`--sim` (a global flag) runs `build`/`flash`/`test`/`hil`/`run` with no toolchain
or hardware; drop it (and add `--port`/`--workbench`) for real boards.

## Exit codes (stable contract)

| code | meaning |
|------|---------|
| 0 | success |
| 1 | verb-level failure (invalid board, build/test failed) |
| 2 | usage / bad input |
| 127 | a required external tool (`idf.py` / `pytest`) is not installed |

## JSON envelope

With `--json`, every verb prints one object: `{"verb": ..., "ok": bool, "exit_code": int, ...}` plus verb-specific fields (`detail`, `board`, `out`, `tools`, ...). This is what the agent and CI parse.

## Wiring

`mcuflow` finds its sibling deliverables relative to the repo root (`../board-schema/validate.py`, `../project-template/scaffold.py`). Override with `MCUFLOW_VALIDATOR` / `MCUFLOW_SCAFFOLD` if your layout differs. `build`/`flash`/`monitor` go through the platform adapter (`get_adapter(meta.platform)` — ESP-IDF today, others plug in beside it); `test` shells out to `pytest`; `doctor` tells you what's installed. This keeps the modules decoupled — the conductor wires their contracts, nothing calls across modules directly.
