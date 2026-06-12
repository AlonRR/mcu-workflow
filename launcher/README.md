# launcher — `mcuflow up` (deliverable #4)

The front door. One step to start work: it brings up the containerized **cage**, mounts your project, passes the connected board's USB/serial port through, and starts (or resumes) the agent inside — permissions bypassed *inside* the cage, boundary enforced *at* the wall (see `ARCHITECTURE.md`, Sections 6–7).

## Prerequisites

- **Docker** (Desktop on Windows/macOS, Engine on Linux)
- **Windows only:** WSL2 and [`usbipd-win`](https://github.com/dorssel/usbipd-win) to pass a USB board into the WSL2 backend Docker uses.

Check everything first:

```bash
python up.py doctor          # auto-detects your OS
```

## Use (Windows, with Docker + WSL2)

```powershell
# 1. See what's plugged in and get the bus id
usbipd list

# 2. Preview exactly what the launcher will run (no changes made)
python up.py --project . up --busid <BUSID> --dry-run

# 3. Do it for real (binding a device needs an elevated/admin shell once)
python up.py --project . up --busid <BUSID>
```

The launcher runs `usbipd bind`/`attach` to put the board into WSL2, then `docker run` exposes it to the cage as `/dev/ttyACM0` and starts the agent.

## Use (Linux)

```bash
python up.py --project . up               # auto-selects /dev/ttyACM* or /dev/ttyUSB*
python up.py --project . up --device /dev/ttyACM0   # or name it
```

## Resume vs fresh

Running `up` again **resumes** the existing cage (the project mount persists, so state carries over). Force a clean cage with `--fresh`. Tear it down with `python up.py down`.

## What the cage `docker run` looks like

```
docker run --rm -it --name mcuflow-cage \
  --cap-drop ALL --security-opt no-new-privileges --user <uid:gid> \
  -v <project>:/work -w /work \
  --device /dev/ttyACM0 --group-add dialout \
  espressif/idf:release-v6.0  claude --dangerously-skip-permissions
```

Inside that box the agent has free rein; the worst case is "rebuild the cage." Full egress enforcement (allowlisting proxy + docker network) is deliverable #7 — set `network`/`https_proxy` in `cage.yaml` to route through it.

## Files

- `up.py` — the launcher (subcommands: `up`, `doctor`, `usb`, `down`; global `--dry-run`, `--os`, `--image`, `--name`, `--agent`, `--project`).
- `cage.yaml` — default configuration (image, container name, agent, boundary flags).
- `Dockerfile` — starter cage image (ESP-IDF + pytest-embedded + agent client).

## Verifying

`--dry-run` prints every command without executing, so the plan is fully auditable. The launcher's command composition and OS branching are covered that way; the live `docker`/`usbipd` calls need a real host with Docker + (on Windows) WSL2.
