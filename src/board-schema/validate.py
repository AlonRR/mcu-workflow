#!/usr/bin/env python3
"""
validate.py - friendly validator for board.yml, the single-source-of-truth
contract of the micro-controller workflow.

It checks two things:
  1. Structure   - does the file match board.schema.json? (shape, types, enums)
  2. Semantics   - cross-references a schema can't express, e.g. a device that
                   names a bus which isn't defined in `pins:`, an I2C device
                   missing its address, or two roles fighting over one pin.

Output is plain-language, grouped into ERRORS (block validity) and WARNINGS
(worth a look, but valid). Designed to be readable by someone new to electronics.

Exit codes (stable contract):
  0  valid (warnings allowed)
  1  invalid (one or more errors)
  2  usage / file / dependency problem
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "board.schema.json"


def _die(msg, code=2):
    print("error: " + msg, file=sys.stderr)
    raise SystemExit(code)


def _load_deps():
    try:
        import yaml  # type: ignore
    except ImportError:
        _die("PyYAML is not installed. Run: pip install pyyaml jsonschema")
    try:
        import jsonschema  # type: ignore
    except ImportError:
        _die("jsonschema is not installed. Run: pip install pyyaml jsonschema")
    return yaml, jsonschema


def _humanize_schema_error(err):
    """Turn a jsonschema ValidationError into a plain-language line."""
    loc = "/".join(str(p) for p in err.absolute_path) or "(top level)"
    msg = err.message
    if err.validator == "required":
        return loc + ": missing required field - " + msg
    if err.validator == "additionalProperties":
        return loc + ": unexpected/unknown field - " + msg
    if err.validator == "enum":
        return loc + ": not an allowed value - " + msg
    if err.validator == "type":
        return loc + ": wrong type - " + msg
    return loc + ": " + msg


def _collect_pin_uses(data):
    """Map every physical pin number -> the list of roles that claim it."""
    uses = {}

    def claim(pin, role):
        if isinstance(pin, bool) or not isinstance(pin, int):
            return
        uses.setdefault(pin, []).append(role)

    for name, val in (data.get("pins") or {}).items():
        if isinstance(val, int) and not isinstance(val, bool):
            claim(val, "pins." + name)
        elif isinstance(val, dict):
            for role, pin in val.items():
                claim(pin, "pins." + name + "." + role)

    for dname, dev in (data.get("devices") or {}).items():
        if not isinstance(dev, dict):
            continue
        if "cs" in dev:
            claim(dev["cs"], "devices." + dname + ".cs")
        for role, pin in (dev.get("pins") or {}).items():
            claim(pin, "devices." + dname + ".pins." + role)

    rig = data.get("rig") or {}
    for key in ("dut_reset_gpio", "dut_boot_gpio"):
        if key in rig:
            claim(rig[key], "rig." + key)

    return uses


def semantic_checks(data):
    """Cross-reference checks the JSON Schema can't do. Returns (errors, warnings)."""
    errors = []
    warnings = []

    pins = data.get("pins") or {}
    devices = data.get("devices") or {}
    declared_components = set()
    for item in data.get("components") or []:
        if isinstance(item, str):
            declared_components.add(item.split(":")[0].strip())
        elif isinstance(item, dict):
            declared_components.update(item.keys())

    for dname, dev in devices.items():
        if not isinstance(dev, dict):
            continue
        bus = dev.get("bus")
        # 1. The bus must be a defined pin-group, or a generic 'gpio'/'adc'.
        if bus not in pins and bus not in ("gpio", "adc"):
            known = ", ".join(sorted(pins)) or "none"
            errors.append(
                "devices." + dname + ": bus '" + str(bus) + "' is not defined "
                "under pins: (known buses: " + known + "; or use 'gpio'/'adc')."
            )
        # 2. Bus-specific required wiring.
        if isinstance(bus, str) and bus.startswith("i2c") and "address" not in dev:
            errors.append(
                "devices." + dname + ": an I2C device needs an 'address' (e.g. address: 0x76)."
            )
        if isinstance(bus, str) and bus.startswith("spi") and "cs" not in dev:
            errors.append("devices." + dname + ": an SPI device needs a 'cs' (chip-select) pin.")
        if bus == "gpio" and "pins" not in dev:
            errors.append(
                "devices." + dname + ": a 'gpio' device needs a 'pins' map "
                "(e.g. pins: {in1: 4, in2: 5})."
            )
        # 3. Helpful nudge: driver named but not in components (auto-fillable).
        drv = dev.get("driver")
        if drv and drv not in declared_components:
            warnings.append(
                "devices." + dname + ": driver '" + drv + "' is not in "
                "components: - it will be added automatically when the "
                "project is generated."
            )

    # 4. Physical pin conflicts: one pin claimed by two roles.
    for pin, roles in _collect_pin_uses(data).items():
        if len(roles) > 1:
            warnings.append(
                "pin "
                + str(pin)
                + " is assigned to more than one role: "
                + ", ".join(roles)
                + " - check this is intentional."
            )

    # 5. Low-power sanity: wake_gpio set but 'gpio' not a wake source.
    power = data.get("power") or {}
    if "wake_gpio" in power and "gpio" not in (power.get("wake_sources") or []):
        warnings.append(
            "power.wake_gpio is set but 'gpio' is not in power.wake_sources - "
            "the GPIO wake may not be enabled."
        )

    return errors, warnings


def validate(path):
    yaml, jsonschema = _load_deps()

    if not path.exists():
        _die("file not found: " + str(path))
    if not SCHEMA_PATH.exists():
        _die("schema not found next to validator: " + str(SCHEMA_PATH))

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        _die("could not parse YAML: " + str(e), code=1)

    if not isinstance(data, dict):
        _die("top level of board.yml must be a mapping (key: value).", code=1)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    errors = []
    # Pick the validator class declared by the schema's $schema (portable across
    # jsonschema versions); fall back to the newest available if unknown.
    try:
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
    except Exception:
        validator_cls = getattr(
            jsonschema, "Draft202012Validator", None
        ) or jsonschema.validators.validator_for(schema)
    validator = validator_cls(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        errors.append(_humanize_schema_error(err))

    sem_errors, warnings = semantic_checks(data)
    errors.extend(sem_errors)

    project = (data.get("meta") or {}).get("project", path.name)
    print("Validating " + path.name + "  (project: " + str(project) + ")")
    print("-" * 56)

    for w in warnings:
        print("  ! warning  " + w)
    for e in errors:
        print("  x error    " + e)

    def count(n, noun):
        return str(n) + " " + noun + ("" if n == 1 else "s")

    print("-" * 56)
    if errors:
        summary = "INVALID - " + count(len(errors), "error")
        if warnings:
            summary += ", " + count(len(warnings), "warning")
        print(summary)
        return 1
    if warnings:
        print("VALID - " + count(len(warnings), "warning"))
    else:
        print("VALID - no issues")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate a board.yml against the schema, with friendly errors."
    )
    parser.add_argument("path", type=Path, help="path to a board.yml file")
    args = parser.parse_args(argv)
    return validate(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
# end of file
