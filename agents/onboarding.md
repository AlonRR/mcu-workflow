# Paste this as your first message to Claude Code

> Open this folder in Claude Code on the machine with the two ESP32-C3s plugged
> in, then paste the block below.

---

You are doing the real two-board hardware bring-up for this project. Read
`CLAUDE.md` and `docs/runbook-c3.md` first — they have the full plan and the C3
gotchas. The whole loop already passes in simulation; your job is the real run.

Work in this order, and **stop and show me the output at each checkpoint**:

1. `pytest` — confirm the sim baseline is green.

2. Decide the run mode and tell me which:
   - **Native** if `idf.py` is on PATH (run directly), or
   - **Caged** (preferred): `docker build -t mcuflow-cage:idf6 -f src/launcher/Dockerfile launcher/`,
     set `image: mcuflow-cage:idf6` in `cage.yaml`, then
     `python src/mcuflow/mcuflow.py up up --busid <B1> --busid <B2>`
     (on Windows run `usbipd list` first; pass the two C3 bus IDs).

3. Identify the boards — **don't assume which COM/ACM is which**. Flash the
   satellite firmware (`src/satellite/firmware-idf/`, `idf.py set-target esp32c3`)
   to one board, then for each candidate port start
   `mcuflow workbench --satellite <PORT>` and POST `/api/satellite/ping`. The
   port that returns `{"fw":"sat-idf-0.1"}` is the **satellite**; the other is
   the **DUT**. Report both ports.

4. With the satellite confirmed and its workbench running, do the DUT loop:
   `mcuflow run examples/board-c3.yml --port <DUT_PORT> --workbench http://127.0.0.1:8080`
   (no `--sim`).

5. Read the **DUT serial** (`idf.py -p <DUT_PORT> monitor`) and confirm two
   lines appear while the satellite's AP is up: `app_main started` and
   `wifi: connected to 'mcuflow-test', got ip ...`. Paste them.

Expected friction (all noted in CLAUDE.md): ESP-IDF component `REQUIRES` names
may differ on your point release — if a build fails, fix the named REQUIRES in
`main/CMakeLists.txt`. The C3's native USB re-enumerates around flashes — re-list
ports if one won't open; hold BOOT (GPIO9) low to force download mode if needed.

Do not push to remote or change the boundary settings in `cage.yaml`. When step
5 shows both lines, the real end-to-end run is done — summarize what you saw.
