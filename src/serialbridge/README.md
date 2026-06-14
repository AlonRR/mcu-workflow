# serialbridge — `mcuflow bridge`

Serve a local serial port over the network (RFC2217) so a board on this host can
be flashed or monitored from another machine. Wraps esptool's
`esp_rfc2217_server`.

```sh
# on the host with the board plugged in:
mcuflow bridge --port COM6 --tcp 4000

# on another machine on the LAN:
mcuflow flash examples/board-c3.yml --port rfc2217://<host>:4000
mcuflow monitor --port rfc2217://<host>:4000
```

`esptool`/`idf.py` (via pyserial) accept `rfc2217://` URLs natively, so nothing
else changes on the flashing side. The server is single-connection: it serves
one board and waits for the next client when a connection ends.

## Note on the C3's native USB

The serial **data path** works over RFC2217 (verified: a remote `esptool` reads
the chip through the bridge). But auto-reset-into-download-mode relies on DTR/RTS
signaling that the ESP32-C3's native USB-Serial/JTAG does not reproduce over the
network. For the C3, put the board in download mode first — hold BOOT (GPIO9)
while it resets, or pulse it via the satellite GPIO (`/api/gpio/set`) — then
flash over the bridge. Boards behind a classic USB-UART bridge auto-reset
normally.
