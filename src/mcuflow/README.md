# mcuflow — the conductor CLI (deliverable #2)

`mcuflow` is the single canonical entry point for the workflow — the *deterministic conductor*. It wraps the modular deliverables as verbs with a stable contract: human output by default, one JSON object with `--json`, and documented exit codes. CI, scripts, and the agent all go through it, so behavior never diverges (see `docs/architecture.md`, "Who orchestrates").

## Use

```bash
pip install pyyaml jsonschema
python mcuflow.py validate ../examples/board.yml
python mcuflow.py scaffold ../examples/board.yml -o ./my-project
python mcuflow.py env doctor
python mcuflow.py --json validate my-board.yml      # machine-readable
```

## Verbs

| Verb | Does | Backed by |
|------|------|-----------|
| `validate <board.yml>` | structure + semantic check | deliverable #1 |
| `scaffold <board.yml> [-o dir]` | generate an ESP-IDF project | deliverable #3 |
| `build [--path .]` | `idf.py build` | ESP-IDF |
| `flash [--path .] [--port P]` | `idf.py flash` | ESP-IDF |
| `monitor [--path .] [--port P]` | `idf.py monitor` (interactive) | ESP-IDF |
| `test <pyfile> [--target chip]` | pytest-embedded HIL run | pytest-embedded |
| `env doctor` | report toolchain availability | — |

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

`mcuflow` finds its sibling deliverables relative to the repo root (`../board-schema/validate.py`, `../project-template/scaffold.py`). Override with `MCUFLOW_VALIDATOR` / `MCUFLOW_SCAFFOLD` if your layout differs. `build`/`flash`/`monitor`/`test` shell out to `idf.py`/`pytest`; `env doctor` tells you what's installed. This keeps the modules decoupled — the conductor wires their contracts, nothing calls across modules directly.
