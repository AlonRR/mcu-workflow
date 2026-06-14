#!/usr/bin/env python3
"""mcuflow debug - start an OpenOCD GDB server for the board (JTAG/debug).

ESP32-C3/S3/C6/H2 have a built-in USB-JTAG, so OpenOCD attaches over the same
USB cable - no external probe. This launches OpenOCD with the right board config;
connect your debugger to the GDB server it opens on :3333, e.g.

    riscv32-esp-elf-gdb build/<app>.elf -ex "target remote :3333"

OpenOCD ships with ESP-IDF (`. $IDF_PATH/export.sh` puts it on PATH, or install
via idf-tools). On Windows the USB-JTAG interface needs a WinUSB driver (use
Zadig once on the "USB JTAG/serial debug unit (Interface 2)").
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

# Chips with a built-in USB-JTAG -> their stock OpenOCD board config. Others
# need an external probe; pass --board with the right config.
CHIP_CFG = {
    "esp32c3": "board/esp32c3-builtin.cfg",
    "esp32s3": "board/esp32s3-builtin.cfg",
    "esp32c6": "board/esp32c6-builtin.cfg",
    "esp32h2": "board/esp32h2-builtin.cfg",
    "esp32": "board/esp32-wrover-kit-3.3v.cfg",
    "esp32s2": "board/esp32s2-kaluga-1.cfg",
}


def build_cmd(chip, board=None, openocd="openocd"):
    """OpenOCD argv for a chip, or None if the chip is unknown and no --board."""
    cfg = board or CHIP_CFG.get(chip)
    if not cfg:
        return None
    return [openocd, "-f", cfg]


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="mcuflow debug", description="start an OpenOCD GDB server for the board"
    )
    ap.add_argument("--chip", default="esp32c3", help="target chip (default esp32c3)")
    ap.add_argument("--board", default=None, help="OpenOCD board config (overrides --chip default)")
    ap.add_argument("--openocd", default="openocd", help="path to the openocd binary")
    args = ap.parse_args(argv)

    cmd = build_cmd(args.chip, args.board, args.openocd)
    if cmd is None:
        print(
            "x unknown chip '" + args.chip + "'; pass --board <openocd-config>",
            file=sys.stderr,
        )
        return 2
    if shutil.which(args.openocd) is None:
        print(
            "x openocd not found. It ships with ESP-IDF - run `. $IDF_PATH/export.sh` "
            "(or install via idf-tools). On Windows, give the USB-JTAG interface a "
            "WinUSB driver with Zadig first.",
            file=sys.stderr,
        )
        return 127
    print(
        "starting OpenOCD (" + (args.board or CHIP_CFG.get(args.chip)) + ") - GDB server on :3333"
    )
    print('connect: <gdb> build/<app>.elf -ex "target remote :3333"')
    try:
        return subprocess.run(cmd).returncode
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
