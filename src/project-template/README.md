# project-template — scaffold generator (deliverable #3)

Turns a `board.yml` (deliverable #1) into a buildable ESP-IDF project. This is the conductor's `scaffold` verb: deterministic, no model needed, same output every run.

## Use

Via the conductor (deps come from the project `.venv`; see the root README — no
pre-existing Python needed):

```bash
mcuflow validate my-board.yml          # validate first (recommended)
mcuflow scaffold my-board.yml -o ./my-project
```

## What it generates

```
<out>/
  CMakeLists.txt              top-level ESP-IDF project
  sdkconfig.defaults          build overrides + power profile, diffable
  main/
    CMakeLists.txt            component registration
    idf_component.yml         deps auto-filled from components: and devices[].driver
    main.c                    app_main with per-bus / per-device init stubs
  pytest_<project>.py         pytest-embedded HIL skeleton (expects the boot_string)
  README.md                   build/flash instructions for the generated project
```

## How board.yml maps to the project

- `meta.project` → CMake `project()` name; `meta.chip` → `idf.py set-target`.
- `pins.i2c*/spi*/uart*` → matching driver includes + commented init stubs with the actual pin numbers; a `*led*` simple pin becomes a blink loop.
- `devices[].driver` + `components:` → `idf_component.yml` dependencies (de-duplicated).
- `build.sdkconfig` and `power:` → `sdkconfig.defaults` (sleep → `CONFIG_PM_ENABLE`, etc.).
- `test.boot_string` / `test.needs` → the pytest skeleton's expectation and routing note.

## Verifying

The scaffold's structure and generated YAML/Python are checked in the project's tests. The definitive build test is `idf.py build` on a machine with ESP-IDF installed (or in CI, deliverable #11) — the sandbox has no ESP-IDF toolchain or headers.

## Notes

`main.c` is a skeleton: bus init is left as clearly marked `TODO`s with the right pins already filled in. Fill in the driver calls (or let the agent do it, grounded by the Docs MCP server).
