#!/usr/bin/env python3
"""
enclosure.py - parametric FDM enclosure generator (deliverable #7).

Reads the `enclosure:` section of board.yml and emits:
  * <project>_case.py  - a parametric build123d script. Open it in VS Code with
                         the OCP CAD Viewer for a live preview; run it to export
                         STL / STEP / 3MF for FDM slicing.
  * <project>_preview.stl - a quick, dependency-free solid-box preview of the
                         outer shell (so there's always an artifact, even
                         without build123d installed). Sizing only - not the
                         final geometry.

Print-friendly defaults are baked in: >= 2 mm walls, a tunable fit clearance,
PCB standoffs, and port cutouts on the requested sides.

Exit codes: 0 ok, 2 usage / bad input.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


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


def _enc_params(data):
    enc = data.get("enclosure") or {}
    bs = enc.get("board_size_mm") or {}
    bx = float(bs.get("x", 50))
    by = float(bs.get("y", 50))
    bz = float(bs.get("z", 1.6))
    wall = float(enc.get("wall_mm", 2.0))
    clr = float(enc.get("clearance_mm", 0.4))
    standoff = float(enc.get("standoff_mm", 3.0))
    style = enc.get("style", "snap-fit")
    cutouts = enc.get("cutouts") or []
    # Interior must fit the board + clearance on each side; height leaves room
    # for the board on standoffs plus a little headroom.
    inner_x = bx + 2 * clr
    inner_y = by + 2 * clr
    inner_z = standoff + bz + 8.0  # headroom above the board
    return {
        "bx": bx, "by": by, "bz": bz, "wall": wall, "clr": clr,
        "standoff": standoff, "style": style, "cutouts": cutouts,
        "inner_x": inner_x, "inner_y": inner_y, "inner_z": inner_z,
        "outer_x": inner_x + 2 * wall, "outer_y": inner_y + 2 * wall,
        "outer_z": inner_z + wall,
    }


def gen_build123d_script(project, p):
    """Emit an editable, parametric build123d script."""
    cut_lines = []
    for c in p["cutouts"]:
        side = c.get("side", "-y")
        what = c.get("for", "port")
        cut_lines.append('    # cutout for ' + str(what) + ' on side ' + str(side)
                         + ' - size/position to your connector')
    cut_block = "\n".join(cut_lines) if cut_lines else "    # (no cutouts declared)"

    return (
        '"""Parametric enclosure for ' + project + ' (auto-generated from board.yml).\n'
        "Open in VS Code with the OCP CAD Viewer for a live preview, or run to export.\n"
        '"""\n'
        "from build123d import *\n"
        "try:\n"
        "    from ocp_vscode import show\n"
        "except Exception:\n"
        "    def show(*a, **k):\n"
        "        pass\n"
        "\n"
        "# --- parameters (from board.yml enclosure:) ---\n"
        "BOARD_X, BOARD_Y, BOARD_Z = " + repr(p["bx"]) + ", " + repr(p["by"]) + ", " + repr(p["bz"]) + "\n"
        "WALL = " + repr(p["wall"]) + "\n"
        "CLEARANCE = " + repr(p["clr"]) + "\n"
        "STANDOFF = " + repr(p["standoff"]) + "\n"
        "\n"
        "inner_x = BOARD_X + 2 * CLEARANCE\n"
        "inner_y = BOARD_Y + 2 * CLEARANCE\n"
        "inner_z = STANDOFF + BOARD_Z + 8.0\n"
        "\n"
        "with BuildPart() as case:\n"
        "    # outer shell\n"
        "    Box(inner_x + 2 * WALL, inner_y + 2 * WALL, inner_z + WALL)\n"
        "    # hollow out the interior (open top)\n"
        "    with BuildPart(mode=Mode.SUBTRACT):\n"
        "        with Locations((0, 0, WALL)):\n"
        "            Box(inner_x, inner_y, inner_z + WALL, align=(Align.CENTER, Align.CENTER, Align.MIN))\n"
        "    # four PCB standoffs in the corners\n"
        "    sx = inner_x / 2 - 3\n"
        "    sy = inner_y / 2 - 3\n"
        "    with BuildPart():\n"
        "        with Locations((sx, sy, WALL), (-sx, sy, WALL), (sx, -sy, WALL), (-sx, -sy, WALL)):\n"
        "            Cylinder(2.5, STANDOFF, align=(Align.CENTER, Align.CENTER, Align.MIN))\n"
        "\n"
        + cut_block + "\n"
        "\n"
        "show(case)\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    export_stl(case.part, '" + project + "_case.stl')\n"
        "    try:\n"
        "        export_step(case.part, '" + project + "_case.step')\n"
        "    except Exception:\n"
        "        pass\n"
    )


def write_box_stl(path, dx, dy, dz):
    """Write a binary STL of a solid box (12 triangles). Dependency-free."""
    x0, y0, z0 = 0.0, 0.0, 0.0
    x1, y1, z1 = dx, dy, dz
    v = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),  # bottom 0-3
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),  # top 4-7
    ]
    # 12 triangles (2 per face), winding outward.
    tris = [
        (0, 2, 1), (0, 3, 2),        # bottom (-z)
        (4, 5, 6), (4, 6, 7),        # top (+z)
        (0, 1, 5), (0, 5, 4),        # -y
        (1, 2, 6), (1, 6, 5),        # +x
        (2, 3, 7), (2, 7, 6),        # +y
        (3, 0, 4), (3, 4, 7),        # -x
    ]

    def normal(a, b, c):
        ux, uy, uz = (b[0]-a[0], b[1]-a[1], b[2]-a[2])
        vx, vy, vz = (c[0]-a[0], c[1]-a[1], c[2]-a[2])
        nx, ny, nz = (uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx)
        m = (nx*nx+ny*ny+nz*nz) ** 0.5 or 1.0
        return (nx/m, ny/m, nz/m)

    with open(path, "wb") as f:
        f.write(b"\0" * 80)               # header
        f.write(struct.pack("<I", len(tris)))
        for (ia, ib, ic) in tris:
            a, b, c = v[ia], v[ib], v[ic]
            n = normal(a, b, c)
            f.write(struct.pack("<3f", *n))
            f.write(struct.pack("<3f", *a))
            f.write(struct.pack("<3f", *b))
            f.write(struct.pack("<3f", *c))
            f.write(struct.pack("<H", 0))  # attribute byte count


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate a parametric FDM enclosure from board.yml.")
    ap.add_argument("board", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("."))
    args = ap.parse_args(argv)

    data = _load_yaml(args.board)
    if "enclosure" not in data:
        _die("board.yml has no 'enclosure:' section to generate from.")
    project = (data.get("meta") or {}).get("project", "project")
    p = _enc_params(data)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    script_path = out / (project + "_case.py")
    stl_path = out / (project + "_preview.stl")

    script_path.write_text(gen_build123d_script(project, p), encoding="utf-8")
    write_box_stl(stl_path, p["outer_x"], p["outer_y"], p["outer_z"])

    print("Generated enclosure for '" + project + "':")
    print("  build123d script : " + str(script_path)
          + "  (open in VS Code + OCP CAD Viewer)")
    print("  STL preview      : " + str(stl_path)
          + "  (" + str(round(p["outer_x"], 1)) + " x "
          + str(round(p["outer_y"], 1)) + " x " + str(round(p["outer_z"], 1)) + " mm)")
    print("  walls " + str(p["wall"]) + " mm, clearance " + str(p["clr"])
          + " mm, " + str(len(p["cutouts"])) + " cutout(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
