# debugger — `mcuflow debug`

Start an OpenOCD GDB server for the board so you can step-debug it. The ESP32-C3
(and S3/C6/H2) have a **built-in USB-JTAG**, so OpenOCD attaches over the same
USB cable — no external probe.

```sh
mcuflow debug --chip esp32c3          # OpenOCD with the built-in USB-JTAG config
mcuflow debug --board board/<x>.cfg   # any other OpenOCD board config
```

It opens a GDB server on `:3333`; connect your debugger:

```sh
riscv32-esp-elf-gdb build/<app>.elf -ex "target remote :3333"
```

## Requirements

- **OpenOCD** — ships with ESP-IDF; `. $IDF_PATH/export.sh` puts it on PATH, or
  install via idf-tools. `mcuflow debug` tells you if it's missing.
- **Windows only:** the USB-JTAG interface needs a WinUSB driver. Run Zadig once
  and assign WinUSB to "USB JTAG/serial debug unit (Interface 2)".

## Note

This is a host-side launcher; its command construction is unit-tested, but a live
attach needs OpenOCD installed and (on Windows) the WinUSB driver above, so it
isn't exercised in the hardware-free test suite.
