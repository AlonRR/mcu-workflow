# adapters — platform adapter interface (deliverable #12)

The hinge that keeps the workflow target-agnostic. A `PlatformAdapter` maps the workflow's verbs (`set_target`, `build`, `flash`, `monitor`, `test`) to a specific toolchain, and each method **returns the command argv** rather than executing — so the deterministic conductor (`mcuflow`) runs it and the mapping stays testable.

```python
from adapters import get_adapter
a = get_adapter("esp32")
a.build_cmd(".")                 # -> ['idf.py', '-C', '.', 'build']
a.flash_cmd(".", "/dev/ttyACM0") # -> ['idf.py', '-C', '.', '-p', '/dev/ttyACM0', 'flash']
```

## Adapters

| Platform | Toolchain | Status |
|----------|-----------|--------|
| `esp32` | idf.py / esptool / pytest-embedded | **supported** |
| `stm32` | CMake + arm-none-eabi-gcc + OpenOCD | experimental |
| `rp2040` | Pico SDK (CMake) + picotool | experimental |
| `zephyr` | west + Twister | experimental |

`pytest-embedded` is not ESP-exclusive, so the `test` verb is shared in the base class — only build/flash/target differ per platform.

## How it's chosen

The conductor reads `meta.platform` from `board.yml`, calls `get_adapter(platform)`, and executes the argv each verb returns. Adding a platform is a new adapter file plus a template variant — not a rewrite. The experimental adapters carry the known-good command patterns but are marked `supported = False` until built and tested on real hardware.

## Verifying

Command mapping, the registry, supported flags, and the unknown-platform error are covered by a self-contained test (ESP32 verbs, rp2040 flash, `get_adapter("avr")` raising). Real builds for the experimental platforms need their toolchains on a host.
