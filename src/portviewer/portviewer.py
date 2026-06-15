#!/usr/bin/env python3
"""mcuflow ports - a viewer that makes COM-port passing visible.

Two identical ESP32-C3 boards show up as anonymous COMx names, and the tool
otherwise picks/passes them silently. This is a *viewer*: it lists the connected
boards (with the USB serial number that actually tells them apart), shows the
role the tool would give each one and why, the exact `mcuflow` commands that
mapping produces, and a running plain-English log of boards arriving/leaving.

It never flashes, resets, or runs anything - it only looks. Open it on demand
(`mcuflow ports`) or have it pop up when a board appears (`mcuflow ports
--watch`). `--list` prints the same information once as text (no window).
"""

from __future__ import annotations

import argparse
import time

# Espressif native USB-Serial/JTAG (the C3 Super Mini and friends). This VID is
# how we know a port is an ESP32 board rather than some other serial device.
ESPRESSIF_VID = 0x303A
# Common USB-UART bridges - a board *might* be behind one of these, but we can't
# be sure it's an ESP32, so they're flagged "possible" rather than "board".
BRIDGE_VIDS = {
    0x10C4: "CP210x USB-UART",
    0x1A86: "CH340 USB-UART",
    0x0403: "FTDI USB-UART",
}

WORKBENCH_URL = "http://127.0.0.1:6283"
DEFAULT_BOARD = "examples/board-c3.yml"


def list_ports_info():
    """Return a list of port dicts, or [] if pyserial is unavailable.

    Each dict: device, vid, pid, serial, description, manufacturer.
    """
    try:
        from serial.tools import list_ports  # pyserial
    except ImportError:
        return []
    out = []
    for p in list_ports.comports():
        out.append(
            {
                "device": p.device,
                "vid": p.vid,
                "pid": p.pid,
                "serial": p.serial_number,
                "description": p.description or "",
                "manufacturer": p.manufacturer or "",
            }
        )
    out.sort(key=lambda d: d["device"])
    return out


def classify(port):
    """Return (kind, label): kind is 'board' | 'possible' | 'other'."""
    if port["vid"] == ESPRESSIF_VID:
        return "board", "ESP32 (Espressif USB-JTAG)"
    if port["vid"] in BRIDGE_VIDS:
        return "possible", "possible board via " + BRIDGE_VIDS[port["vid"]]
    return "other", "other serial device"


def boards(ports):
    """The ports that are (or might be) ESP32 boards, board first."""
    rank = {"board": 0, "possible": 1, "other": 2}
    cand = [p for p in ports if classify(p)[0] in ("board", "possible")]
    return sorted(cand, key=lambda p: (rank[classify(p)[0]], p["device"]))


def suggest_roles(ports):
    """Map device -> role with an honest reason for the whole set.

    Returns (mapping, reason). The DUT/satellite split is a *stable guess* - the
    boards are identical, so without probing their firmware the tool can't truly
    know which is which; the order is by serial number so it stays consistent.
    """
    b = boards(ports)
    if not b:
        return {}, "no ESP32 board detected - plug one in (or check the cable)"
    if len(b) == 1:
        return {b[0]["device"]: "DUT"}, "one board found - treated as the DUT"
    ordered = sorted(b, key=lambda p: (p["serial"] or "", p["device"]))
    dut, sat = ordered[0]["device"], ordered[1]["device"]
    reason = (
        "two boards found; assigned by serial-number order so it stays stable "
        "(swap with --port/--satellite if backwards)"
    )
    extra = [p["device"] for p in ordered[2:]]
    if extra:
        reason += "; ignoring extra board(s): " + ", ".join(extra)
    return {dut: "DUT", sat: "satellite"}, reason


def roles_to_ports(mapping):
    """Decode a {device: role} mapping into (dut_device, satellite_device).

    The single place the role strings are turned back into ports, so callers
    (render_commands here, the run auto-detect in mcuflow) don't each re-encode
    the "DUT"/"satellite" literals.
    """
    dut = next((d for d, r in mapping.items() if r == "DUT"), None)
    sat = next((d for d, r in mapping.items() if r == "satellite"), None)
    return dut, sat


def render_commands(mapping, board_yml=DEFAULT_BOARD):
    """The mcuflow commands the current port mapping implies (display only)."""
    dut, sat = roles_to_ports(mapping)
    lines = []
    if sat:
        lines.append("mcuflow workbench --satellite " + sat)
    if dut and sat:
        lines.append(
            "mcuflow run " + board_yml + " --port " + dut + " --workbench " + WORKBENCH_URL
        )
    elif dut:
        lines.append("mcuflow run " + board_yml + " --port " + dut + "  (no satellite: add --sim)")
    if not lines:
        lines.append("# connect a board to see the command")
    return lines


def diff_ports(prev, cur):
    """Plain-English connect/disconnect events between two port snapshots."""
    pmap = {p["device"]: p for p in prev}
    cmap = {p["device"]: p for p in cur}
    events = []
    for dev in cmap:
        if dev not in pmap:
            kind, label = classify(cmap[dev])
            ser = cmap[dev]["serial"]
            tail = " (serial " + ser + ")" if ser else ""
            events.append("+ " + dev + " connected: " + label + tail)
    for dev in pmap:
        if dev not in cmap:
            events.append("- " + dev + " disconnected")
    return events


def has_relevant(ports):
    """True if any port is (or might be) an ESP32 board - used for auto-pop."""
    return any(classify(p)[0] in ("board", "possible") for p in ports)


# --- text mode (no window; headless-safe and testable) ---------------------


def format_report(ports):
    """The same view as the GUI, rendered as plain text."""
    lines = []
    b = boards(ports)
    lines.append("boards found: " + str(len(b)) + "   (serial ports: " + str(len(ports)) + ")")
    lines.append("")
    mapping, reason = suggest_roles(ports)
    for p in ports:
        kind, label = classify(p)
        role = mapping.get(p["device"], "")
        flag = {"board": "[board]", "possible": "[maybe]", "other": "[ -- ]"}[kind]
        lines.append(
            "  %s %-7s %-28s serial=%-16s %s"
            % (flag, p["device"], (p["description"] or label)[:28], p["serial"] or "-", role)
        )
    lines.append("")
    lines.append("why: " + reason)
    lines.append("")
    lines.append("commands this mapping implies:")
    for c in render_commands(mapping):
        lines.append("  " + c)
    return "\n".join(lines)


def report(ports=None):
    """A structured snapshot of the same view (for --json / programmatic use).

    Shape: {ports: [{device, kind, label, role, serial, vid, pid, description,
    manufacturer}], boards: <count>, mapping: {device: role}, reason: <str>,
    commands: [<str>], dut: <device|null>, satellite: <device|null>}.
    The single source the extension's Boards tree and auto-detect consume.
    """
    if ports is None:
        ports = list_ports_info()
    mapping, reason = suggest_roles(ports)
    rows = []
    for p in ports:
        kind, label = classify(p)
        rows.append(
            {
                "device": p["device"],
                "kind": kind,
                "label": label,
                "role": mapping.get(p["device"], ""),
                "serial": p["serial"],
                "vid": p["vid"],
                "pid": p["pid"],
                "description": p["description"],
                "manufacturer": p["manufacturer"],
            }
        )
    dut, sat = roles_to_ports(mapping)
    return {
        "ports": rows,
        "boards": len(boards(ports)),
        "mapping": mapping,
        "reason": reason,
        "commands": render_commands(mapping),
        "dut": dut,
        "satellite": sat,
    }


def run_list():
    print(format_report(list_ports_info()))
    return 0


def run_json():
    import json

    print(json.dumps(report(), indent=2))
    return 0


# --- GUI mode --------------------------------------------------------------


def run_gui(watch=False, poll_ms=1000):
    """Open the tkinter viewer. In watch mode it starts hidden and pops up when
    the first ESP32 board appears. Falls back to text mode if there's no GUI."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:  # no Tk / no display
        print("note: no GUI available (" + type(exc).__name__ + "); showing text view.\n")
        return run_list()

    root = tk.Tk()
    root.title("mcuflow - COM port viewer")
    root.geometry("760x460")
    state = {"ports": [], "shown": not watch}

    header = ttk.Label(root, text="", font=("Segoe UI", 10, "bold"))
    header.pack(anchor="w", padx=10, pady=(10, 4))

    cols = ("port", "type", "desc", "serial", "role")
    tree = ttk.Treeview(root, columns=cols, show="headings", height=7)
    for c, w in zip(cols, (70, 90, 250, 150, 90)):
        tree.heading(c, text=c.capitalize())
        tree.column(c, width=w, anchor="w")
    tree.pack(fill="x", padx=10)

    why = ttk.Label(root, text="", foreground="#555", wraplength=720, justify="left")
    why.pack(anchor="w", padx=10, pady=(6, 0))

    cmd_box = tk.Text(root, height=3, wrap="none", bg="#f4f4f4")
    cmd_box.pack(fill="x", padx=10, pady=(6, 0))

    def copy_cmds():
        root.clipboard_clear()
        root.clipboard_append(cmd_box.get("1.0", "end").strip())

    bar = ttk.Frame(root)
    bar.pack(fill="x", padx=10, pady=4)
    ttk.Button(bar, text="Refresh", command=lambda: refresh(force=True)).pack(side="left")
    ttk.Button(bar, text="Copy commands", command=copy_cmds).pack(side="left", padx=6)

    ttk.Label(root, text="Activity", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10)
    log = tk.Text(root, height=8, state="disabled", bg="#101418", fg="#cfe")
    log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def say(msg):
        log.configure(state="normal")
        log.insert("end", time.strftime("%H:%M:%S ") + msg + "\n")
        log.see("end")
        log.configure(state="disabled")

    def render(ports):
        b = boards(ports)
        header.configure(
            text="boards found: " + str(len(b)) + "    (serial ports: " + str(len(ports)) + ")"
        )
        mapping, reason = suggest_roles(ports)
        tree.delete(*tree.get_children())
        for p in ports:
            kind, label = classify(p)
            tag = {"board": "board", "possible": "maybe", "other": "other"}[kind]
            tree.insert(
                "",
                "end",
                values=(
                    p["device"],
                    {"board": "ESP32", "possible": "maybe", "other": "serial"}[kind],
                    p["description"] or label,
                    p["serial"] or "-",
                    mapping.get(p["device"], ""),
                ),
                tags=(tag,),
            )
        tree.tag_configure("board", background="#e8f5e9")
        tree.tag_configure("maybe", background="#fff8e1")
        why.configure(text="why: " + reason)
        cmd_box.delete("1.0", "end")
        cmd_box.insert("1.0", "\n".join(render_commands(mapping)))

    def refresh(force=False):
        cur = list_ports_info()
        for ev in diff_ports(state["ports"], cur):
            say(ev)
        if force and not diff_ports(state["ports"], cur):
            say("refreshed - no change")
        state["ports"] = cur
        render(cur)
        if watch and not state["shown"] and has_relevant(cur):
            root.deiconify()
            root.lift()
            root.attributes("-topmost", True)
            root.after(1200, lambda: root.attributes("-topmost", False))
            state["shown"] = True
            say("a board appeared - opening the viewer")

    def tick():
        refresh()
        root.after(poll_ms, tick)

    if watch:
        root.withdraw()
        say("watching for a board ...")
    say("viewer started")
    refresh()
    root.after(poll_ms, tick)
    root.mainloop()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="mcuflow ports", description="View connected boards and how their COM ports map."
    )
    ap.add_argument("--list", action="store_true", help="print the view once as text (no window)")
    ap.add_argument("--json", action="store_true", help="print the view once as JSON (no window)")
    ap.add_argument(
        "--watch", action="store_true", help="open hidden and pop up when a board is plugged in"
    )
    args = ap.parse_args(argv)
    if args.json:
        return run_json()
    if args.list:
        return run_list()
    return run_gui(watch=args.watch)


if __name__ == "__main__":
    raise SystemExit(main())
