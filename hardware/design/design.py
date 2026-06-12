#!/usr/bin/env python3
"""
design.py - Stage 0 hardware-design helpers (deliverable #6).

The deterministic pieces of the novice-friendly design assistant. The
"describe your idea -> choose a board + modules" reasoning is the agent's job
(see SKILL.md); this tool turns the chosen parts (as recorded in board.yml)
into buyable, wireable, powerable output:

  links  <part>        vendor search URLs for a part
  bom    <board.yml>   bill of materials with purchase links
  wiring <board.yml>   module-pin -> board-pin connection guide
  power  <board.yml>   rough power budget + supply recommendation

Human output by default; one JSON object with --json.
Exit codes: 0 ok, 2 usage / bad input.

NOTE on links: vendor *search* URLs are generated deterministically here.
Specific product links and live prices are NOT fabricated - the agent fetches
those with web search at request time (see SKILL.md).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import quote_plus

HERE = Path(__file__).resolve().parent
PARTS_DB = HERE / "parts_db.yaml"

VENDORS = {
    "aliexpress": "https://www.aliexpress.com/w/wholesale?SearchText={q}",
    "amazon": "https://www.amazon.com/s?k={q}",
    "adafruit": "https://www.adafruit.com/?q={q}",
}

DEFAULT_MCU_MA = 80     # rough active draw if the board is unknown
DEFAULT_DEV_MA = 20     # rough draw for an unknown peripheral module


def _die(msg, code=2):
    print("error: " + msg, file=sys.stderr)
    raise SystemExit(code)


def _load_yaml(path):
    try:
        import yaml  # type: ignore
    except ImportError:
        _die("PyYAML is not installed. Run: pip install pyyaml")
    if not path.exists():
        _die("file not found: " + str(path))
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        _die("top level of board.yml must be a mapping.")
    return data


def _load_parts_db():
    if not PARTS_DB.exists():
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}
    return yaml.safe_load(PARTS_DB.read_text(encoding="utf-8")) or {}


def links_for(part):
    q = quote_plus(str(part) + " module")
    return {v: url.format(q=q) for v, url in VENDORS.items()}


# --- subcommands -----------------------------------------------------------

def cmd_links(args):
    links = links_for(args.part)
    if args.json:
        print(json.dumps({"part": args.part, "links": links}))
    else:
        print("Search links for '" + args.part + "':")
        for v, url in links.items():
            print("  " + v + ": " + url)
        print("(specific products + live prices: ask the agent to web-search)")
    return 0


def _bom_items(data):
    items = []
    board = (data.get("meta") or {}).get("board") or (data.get("meta") or {}).get("chip")
    if board:
        items.append({"name": board, "qty": 1, "role": "main board"})
    for dname, dev in (data.get("devices") or {}).items():
        if isinstance(dev, dict):
            items.append({"name": dev.get("part", dname), "qty": 1, "role": dname})
    return items


def cmd_bom(args):
    data = _load_yaml(args.board)
    items = _bom_items(data)
    for it in items:
        it["links"] = links_for(it["name"])
    if args.json:
        print(json.dumps({"project": (data.get("meta") or {}).get("project"),
                          "bom": items}))
    else:
        print("Bill of materials for '" + str((data.get("meta") or {}).get("project")) + "':")
        for it in items:
            print("  - " + str(it["qty"]) + "x " + it["name"]
                  + "  (" + it["role"] + ")")
            print("      buy: " + it["links"]["aliexpress"])
        print("(prices vary by region; ask the agent for live product links)")
    return 0


def _bus_pins(data, bus_name):
    val = (data.get("pins") or {}).get(bus_name)
    return val if isinstance(val, dict) else {}


def _wiring_rows(data):
    rows = []  # (from, to)
    devices = data.get("devices") or {}
    for dname, dev in devices.items():
        if not isinstance(dev, dict):
            continue
        bus = dev.get("bus")
        part = dev.get("part", dname)
        if isinstance(bus, str) and bus.startswith("i2c"):
            bp = _bus_pins(data, bus)
            if "sda" in bp:
                rows.append((part + ".SDA", "board GPIO" + str(bp["sda"])))
            if "scl" in bp:
                rows.append((part + ".SCL", "board GPIO" + str(bp["scl"])))
        elif isinstance(bus, str) and bus.startswith("spi"):
            bp = _bus_pins(data, bus)
            for sig in ("mosi", "miso", "sclk"):
                if sig in bp:
                    rows.append((part + "." + sig.upper(), "board GPIO" + str(bp[sig])))
            if "cs" in dev:
                rows.append((part + ".CS", "board GPIO" + str(dev["cs"])))
        elif bus == "gpio":
            for role, pin in (dev.get("pins") or {}).items():
                rows.append((part + "." + role, "board GPIO" + str(pin)))
        # power rails (every module needs them)
        rows.append((part + ".VCC", "board 3V3"))
        rows.append((part + ".GND", "board GND"))
    return rows


def cmd_wiring(args):
    data = _load_yaml(args.board)
    rows = _wiring_rows(data)
    if args.json:
        print(json.dumps({"project": (data.get("meta") or {}).get("project"),
                          "connections": [{"from": a, "to": b} for a, b in rows]}))
    else:
        print("Wiring guide for '" + str((data.get("meta") or {}).get("project")) + "':")
        if not rows:
            print("  (no devices declared)")
        width = max((len(a) for a, _ in rows), default=0)
        for a, b in rows:
            print("  " + a.ljust(width) + "  ->  " + b)
        print("Double-check VCC voltage per module (3V3 vs 5V) before powering on.")
    return 0


def _parse_mah(text):
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*mah", str(text).lower())
    return float(m.group(1)) if m else None


def cmd_power(args):
    data = _load_yaml(args.board)
    db = _load_parts_db()
    parts = db.get("parts", {}) if isinstance(db, dict) else {}

    breakdown = []
    unknown = []
    meta = data.get("meta") or {}
    board = meta.get("board") or meta.get("chip")
    if board in parts:
        ma = float(parts[board].get("typical_current_ma", DEFAULT_MCU_MA))
    else:
        ma = DEFAULT_MCU_MA
        unknown.append(str(board))
    breakdown.append({"item": str(board), "ma": ma})

    for dname, dev in (data.get("devices") or {}).items():
        if not isinstance(dev, dict):
            continue
        part = dev.get("part", dname)
        if part in parts:
            d_ma = float(parts[part].get("typical_current_ma", DEFAULT_DEV_MA))
        else:
            d_ma = DEFAULT_DEV_MA
            unknown.append(str(part))
        breakdown.append({"item": str(part), "ma": d_ma})

    total = sum(b["ma"] for b in breakdown)
    recommended_ma = int(math.ceil(total * 1.3))

    cap_mah = _parse_mah((data.get("hardware") or {}).get("power_source"))
    runtime_h = round(cap_mah / total, 1) if (cap_mah and total) else None

    sleep = (data.get("power") or {}).get("sleep")
    note_sleep = (sleep in ("light", "deep"))

    result = {
        "project": meta.get("project"),
        "breakdown_ma": breakdown,
        "active_total_ma": round(total, 1),
        "recommended_supply_ma": recommended_ma,
        "battery_mah": cap_mah,
        "active_runtime_hours_estimate": runtime_h,
        "unknown_parts": unknown,
        "note": "Rough active-current estimate, not a measurement.",
    }
    if args.json:
        print(json.dumps(result))
    else:
        print("Power budget for '" + str(meta.get("project")) + "' (rough estimate):")
        for b in breakdown:
            print("  " + b["item"].ljust(24) + " ~" + str(b["ma"]) + " mA")
        print("  " + "-" * 32)
        print("  active total            ~" + str(round(total, 1)) + " mA")
        print("  recommend supply >=     " + str(recommended_ma) + " mA")
        if runtime_h is not None:
            print("  battery " + str(int(cap_mah)) + " mAh -> ~"
                  + str(runtime_h) + " h active (much longer with sleep)")
        if note_sleep:
            print("  note: '" + sleep + "' sleep set - average draw will be far below active.")
        if unknown:
            print("  unknown draw (assumed default): " + ", ".join(unknown))
        print("  This is an estimate to size a supply - measure for the real figure.")
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="design",
        description="Stage 0 hardware-design helpers (BOM, links, wiring, power).")
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    links_p = sub.add_parser("links", help="vendor search URLs for a part")
    links_p.add_argument("part")
    links_p.set_defaults(func=cmd_links)

    b = sub.add_parser("bom", help="bill of materials with links")
    b.add_argument("board", type=Path)
    b.set_defaults(func=cmd_bom)

    w = sub.add_parser("wiring", help="connection guide")
    w.add_argument("board", type=Path)
    w.set_defaults(func=cmd_wiring)

    pw = sub.add_parser("power", help="rough power budget")
    pw.add_argument("board", type=Path)
    pw.set_defaults(func=cmd_power)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
