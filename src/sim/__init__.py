"""Simulation harness: run the whole two-board workflow with no hardware.

This is what makes `mcuflow ... --sim` and the HIL demo work on a plain laptop
(or CI) before any ESP32 is plugged in. Swap the simulator for real ports and
the exact same interface drives the real boards.
"""
