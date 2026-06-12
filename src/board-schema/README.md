# board.yml — schema & validator

This is deliverable #1 of the micro-controller workflow: the **single source of truth** for one project/target, plus a friendly validator. Scaffold, build, flash, test routing, wiring guides, and the enclosure all derive from this one file (see `docs/architecture.md`, Section 3, "The board.yml contract").

## What's here

- `board.schema.json` — the portable contract (JSON Schema 2020-12). Language-agnostic: any tool in any language can validate against it.
- `validate.py` — a human-friendly validator. It checks structure *and* the cross-references a schema can't express, with plain-language errors.
- `examples/board.yml` — a full example using every section.
- `examples/minimal.yml` — the smallest valid file (a blinky).
- `examples/broken.yml` — an intentionally broken file to show the error messages.

## Use

```bash
# pyyaml + jsonschema come from the project's uv .venv (see the root README).
# To run the validator standalone with uv — no pre-installed Python needed:
uv run --no-project --with pyyaml --with jsonschema \
    python validate.py ../../examples/board.yml
```

Exit codes are a stable contract for scripting and CI:

| code | meaning |
|------|---------|
| 0 | valid (warnings allowed) |
| 1 | invalid (one or more errors) |
| 2 | usage / file-not-found / missing dependency |

## What it checks

**Structure** (via the schema): required fields, types, allowed values (e.g. `platform` must be one of `esp32`/`stm32`/`rp2040`/`zephyr`), and no unknown fields.

**Semantics** (cross-references the schema can't do):

- a `devices` entry must name a `bus` that is defined under `pins:` (or the generic `gpio`/`adc`);
- an I2C device needs an `address`; an SPI device needs a `cs` pin; a `gpio` device needs a `pins` map;
- the same physical pin assigned to two roles is flagged as a warning;
- a `driver` named on a device but absent from `components:` is noted (it gets added automatically at generation time);
- `power.wake_gpio` set without `gpio` in `wake_sources` is flagged.

Errors block validity; warnings don't. Only `meta` is required — every other section is optional and omitted when unused, so a blinky and a low-power sensor node use the same one file.
