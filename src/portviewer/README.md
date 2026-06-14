# portviewer — `mcuflow ports`

A small **viewer** that makes COM-port passing visible. Two identical ESP32-C3
boards show up as anonymous `COMx` names, so it's easy to lose track of which one
is the DUT and which is the satellite — and the rest of the tool otherwise picks
and passes them silently. This window just *looks*: it never flashes, resets, or
runs anything.

It shows:

- every connected serial port, with the **USB serial number** that actually
  tells two identical boards apart (boards are highlighted; an Espressif
  USB-JTAG VID `0x303A` is a definite board, a USB-UART bridge is a "maybe");
- the **role** the tool would give each board (DUT / satellite) and a one-line
  **reason** for the guess (honest: the split is by serial-number order, since
  identical boards can't be told apart without probing their firmware);
- the exact **`mcuflow` commands** that mapping implies (copyable);
- a running **plain-English log** of boards arriving and leaving.

## Use

```sh
mcuflow ports            # open the viewer window now
mcuflow ports --watch    # start hidden; pop up when a board is plugged in
mcuflow ports --list     # print the same view once as text (no window)
```

`--list` is also handy on a headless box or over SSH, and is what the tests
exercise. The GUI uses Python's stdlib `tkinter` (no extra dependencies); if no
display is available it falls back to the text view.

## Note

This viewer **explains**, it doesn't act. To actually use the ports it shows,
run the commands it prints (or `mcuflow run … --port <DUT>` / `mcuflow workbench
--satellite <SAT>` yourself). Telling DUT from satellite with certainty needs
the satellite's firmware to answer a probe; that's intentionally out of scope
here to keep the viewer side-effect-free.
