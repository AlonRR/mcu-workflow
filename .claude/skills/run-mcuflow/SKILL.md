---
name: run-mcuflow
description: >
  Run the mcuflow CLI locally and validate board.yml / scaffold output. Use when
  the user says "validate this board.yml", "run mcuflow ...", "scaffold this",
  "does this generate valid YAML", or when you need to check a board file or CLI
  change in this repo. Knows the correct local (non-reexec) invocation.
---

# Run mcuflow locally

mcuflow re-execs itself into its uv-managed `.venv` on every run. When you call
it directly in this repo you must **suppress the re-exec and use the venv's
Python explicitly**, or it will try to bootstrap and may not behave as a plain
script call.

## The invocation

```bash
MCUFLOW_NO_REEXEC=1 .venv/Scripts/python.exe src/mcuflow/mcuflow.py <verb> [args]
```

(`.venv/Scripts/python.exe` is the Windows path in this repo. The deps —
pyyaml, jsonschema, pyserial, esptool — are already in that venv; do **not** use
pip, the venv is uv-managed.)

Common calls:

```bash
MCUFLOW_NO_REEXEC=1 .venv/Scripts/python.exe src/mcuflow/mcuflow.py validate examples/board-c3.yml
MCUFLOW_NO_REEXEC=1 .venv/Scripts/python.exe src/mcuflow/mcuflow.py --json validate examples/board-c3.yml
MCUFLOW_NO_REEXEC=1 .venv/Scripts/python.exe src/mcuflow/mcuflow.py scaffold examples/board-c3.yml -o "$CLAUDE_JOB_DIR/tmp/scaffold-check"
MCUFLOW_NO_REEXEC=1 .venv/Scripts/python.exe src/mcuflow/mcuflow.py --sim run examples/board-c3.yml -o "$CLAUDE_JOB_DIR/tmp/run-check"
```

## Validating generated board.yml

When checking code that *emits* a board.yml (e.g. the VS Code New Project panel),
generate the file, then run it through the real validator above and read the JSON
envelope (`{"verb","ok","exit_code",...}`). Schema facts that matter:

- `meta` requires `project`, `platform`, `chip`. `platform`/`framework` are
  enum-constrained (so `platform: TODO` **fails** validation); `chip` is
  free-form (so `chip: TODO` **passes**).
- A device's `bus` must be declared under `pins:` (an empty map like `i2c0: {}`
  satisfies it).

**Gotcha learned here:** don't let a `console.log`/banner or any stdout get
redirected into the generated YAML file — it lands on line 1 and breaks the YAML
parse. Generate the file cleanly, then validate.

## Exit codes (stable contract)

`0` ok · `1` verb-level failure (invalid board, build/test failed) · `2` usage /
bad input · `127` a required external tool is missing.

## Notes

- Write any scratch output under `$CLAUDE_JOB_DIR/tmp`, not the repo tree.
- `--sim` runs `build`/`flash`/`test`/`hil`/`run` with no toolchain or hardware —
  use it for any check that doesn't need a real board.
- `uv run pytest` (from the repo root) is the hardware-free regression.
