# enclosure — FDM case generator (deliverable #7)

Turns the `enclosure:` section of `board.yml` into a 3D-printable case.

- **`enclosure.py`** — generates two files:
  - `<project>_case.py` — a **parametric build123d script**. Open it in VS Code with the [OCP CAD Viewer](https://github.com/bernhard-42/vscode-ocp-cad-viewer) for a live preview; run it to export STL/STEP/3MF for slicing.
  - `<project>_preview.stl` — a quick, dependency-free solid-box preview of the outer shell (sizing only — always produced, even without build123d).

## Use

```bash
# uv runs it with no pre-installed Python (pyyaml is the generator's only dep):
uv run --no-project --with pyyaml -- python enclosure.py board.yml -o ./case
# then export the model (build123d + the OCP CAD Viewer are heavier, optional deps):
uv run --no-project --with build123d --with ocp_vscode -- python case/<project>_case.py
#   ...or open case/<project>_case.py in VS Code (OCP viewer auto-previews).
#   exports <project>_case.stl / .step
```

## Print-friendly defaults

Baked in so a beginner needn't know them: walls default to 2 mm, a tunable fit `clearance_mm`, PCB corner standoffs, and port cutouts on the requested sides. Tune them in `board.yml`:

```yaml
enclosure:
  style: snap-fit
  board_size_mm: { x: 25.5, y: 51, z: 1.6 }
  wall_mm: 2.0
  clearance_mm: 0.4
  standoff_mm: 3
  cutouts:
    - { for: usb_c, side: -y }
    - { for: status_led, side: +z, type: lightpipe }
```

## Honesty / limits

- The model is only as good as `board_size_mm` and the cutout positions — measure with calipers or use the datasheet.
- The generated cutouts are marked locations you size to your exact connector — geometry is a starting point.
- The real check is a **test print and fit** (the mechanical equivalent of HIL). Slicing/printing stays in your slicer (PrusaSlicer/Orca); the workflow hands off STL/3MF.
- The `_preview.stl` is just the outer box for sizing — the build123d script is the real model.
