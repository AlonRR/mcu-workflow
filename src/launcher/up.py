#!/usr/bin/env python3
"""
mcuflow up - the launcher / front door (deliverable #4).

One step to start work: it brings up the containerized "cage", mounts the
project, passes the connected board's USB/serial port through, and starts (or
resumes) the agent inside - with permissions bypassed inside the cage and the
boundary enforced at the wall (see ARCHITECTURE.md, Sections 6-7).

Subcommands:
  up        start a fresh cage, or resume an existing one (default)
  doctor    check prerequisites (docker, wsl, usbipd, image)
  usb       list candidate boards / show the passthrough plan
  down      stop and remove the cage

Cross-platform:
  Linux   -> board passed with `docker run --device /dev/ttyACM0`
  Windows -> usbipd-win binds the device into WSL2, Docker (WSL2 backend)
             then exposes it to the container as /dev/ttyACM0

`--dry-run` prints every command it would run without executing it, so the
whole plan is auditable. Exit codes: 0 ok, 1 failure, 2 usage, 127 missing tool.
"""
from __future__ import annotations

import argparse
import glob
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_NOTOOL = 0, 1, 2, 127


def _augment_path():
    """Find freshly winget-installed tools (usbipd-win) without a shell restart."""
    if os.name != "nt":
        return
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    for d in [os.path.join(pf, "usbipd-win"),
              os.path.join(pf, "Docker", "Docker", "resources", "bin")]:
        if os.path.isdir(d) and d not in os.environ.get("PATH", ""):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


_augment_path()

DEFAULTS = {
    "image": "espressif/idf:release-v6.0",
    "container": "mcuflow-cage",
    "agent": "claude --dangerously-skip-permissions",
    "mount_to": "/work",
    "network": "",          # docker network with the egress proxy (see #7)
    "https_proxy": "",       # set to enforce allowlisted egress
    "cap_drop_all": True,
    "no_new_privileges": True,
    "non_root": True,
}


def load_config(project_dir):
    cfg = dict(DEFAULTS)
    cfg_path = Path(project_dir) / "cage.yaml"
    if cfg_path.exists():
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
        except ImportError:
            print("note: cage.yaml present but PyYAML missing; using defaults",
                  file=sys.stderr)
    return cfg


def detect_os(override):
    if override and override != "auto":
        return override
    s = platform.system().lower()
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "macos"
    return "linux"


def have(tool):
    return shutil.which(tool) is not None


class Runner:
    """Executes commands, or just prints them in --dry-run."""

    def __init__(self, dry_run):
        self.dry_run = dry_run

    def run(self, cmd, interactive=False, check=False):
        printable = " ".join(cmd)
        if self.dry_run:
            print("  $ " + printable)
            return 0, ""
        proc = subprocess.run(
            cmd,
            stdout=None if interactive else subprocess.PIPE,
            stderr=None if interactive else subprocess.STDOUT,
            text=True,
        )
        out = proc.stdout or ""
        if not interactive and out:
            print(out, end="")
        if check and proc.returncode != 0:
            raise SystemExit(proc.returncode)
        return proc.returncode, out


# --- subcommands -----------------------------------------------------------

def _winget(pkg_id):
    """Best-effort winget install; idempotent (already-installed counts as ok)."""
    if not have("winget"):
        return False, "winget not on PATH; cannot auto-install " + pkg_id
    proc = subprocess.run(
        ["winget", "install", "--id", pkg_id, "-e", "--silent",
         "--accept-source-agreements", "--accept-package-agreements",
         "--disable-interactivity"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    blob = (proc.stdout or "").lower()
    ok = proc.returncode == 0 or "already installed" in blob or "no available upgrade" in blob
    return ok, ("winget " + pkg_id + ": " + ("ok" if ok else "FAILED"))


def cmd_doctor(args, cfg, host_os, runner):
    print("Launcher preflight (" + host_os + "):")
    # With --fix the launcher installs its own cage prerequisites first.
    if getattr(args, "fix", False):
        print("  self-install (--fix):")
        if host_os == "windows":
            if not have("usbipd"):
                print("    " + _winget("dorssel.usbipd-win")[1])
            if not have("docker"):
                print("    " + _winget("Docker.DockerDesktop")[1]
                      + "  (reboot/start Docker Desktop before first cage)")
        if have("docker"):
            print("    pulling cage image " + cfg["image"] + " ...")
            rc, _ = runner.run(["docker", "pull", cfg["image"]])
            print("    docker pull: " + ("ok" if rc == 0 else "FAILED"))
    checks = [("docker", True)]
    if host_os == "windows":
        checks += [("wsl", True), ("usbipd", True)]
    ok = True
    for tool, required in checks:
        present = have(tool)
        ok = ok and (present or not required)
        print("  [" + ("ok " if present else "-- ") + "] " + tool
              + ("" if present else "  (missing)"))
    # Image presence (only meaningful if docker is here and not dry-run).
    if have("docker") and not args.dry_run:
        rc, out = runner.run(["docker", "images", "-q", cfg["image"]])
        print("  image " + cfg["image"] + ": "
              + ("present" if out.strip() else "not pulled (will pull on first up)"))
    else:
        print("  image " + cfg["image"] + ": (not checked)")
    print("ready: " + ("yes" if ok else "no - install the missing tool(s) above"))
    return EXIT_OK if ok else EXIT_NOTOOL


def list_serial_host():
    """Serial ports on this host: Windows COM* or POSIX /dev/tty*."""
    if os.name == "nt":
        try:
            from serial.tools import list_ports  # pyserial
            return sorted(p.device for p in list_ports.comports())
        except Exception:
            return []
    return sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))


def cmd_usb(args, cfg, host_os, runner):
    if host_os == "linux":
        devs = list_serial_host()
        print("Serial devices on this host:")
        for d in devs:
            print("  " + d)
        if not devs:
            print("  (none found - plug a board in)")
    elif host_os == "windows":
        print("Windows USB passthrough uses usbipd-win -> WSL2. List devices with:")
        print("  $ usbipd list")
        print("Then `mcuflow up --busid <BUSID>` binds + attaches it for you.")
    else:
        print("macOS: pass --device for a Linux VM, or use a networked workbench.")
    return EXIT_OK


def windows_usb_steps(busid):
    """Commands that bind+attach a USB device into WSL2 (run by the launcher)."""
    return [
        ["usbipd", "bind", "--busid", busid],          # one-time, needs admin
        ["usbipd", "attach", "--wsl", "--busid", busid],
    ]


def build_run_cmd(cfg, host_os, device, agent_argv, project_dir):
    cmd = ["docker", "run", "--rm", "-it", "--name", cfg["container"]]
    if cfg["cap_drop_all"]:
        cmd += ["--cap-drop", "ALL"]
    if cfg["no_new_privileges"]:
        cmd += ["--security-opt", "no-new-privileges"]
    # Map the container user to the host uid/gid on POSIX. os.getuid is absent on
    # Windows, so guard on it - this lets a Windows host dry-run the linux plan.
    if cfg["non_root"] and host_os != "windows" and hasattr(os, "getuid"):
        cmd += ["--user", str(os.getuid()) + ":" + str(os.getgid())]  # type: ignore[attr-defined]
    # Project mount.
    cmd += ["-v", str(Path(project_dir).resolve()) + ":" + cfg["mount_to"],
            "-w", cfg["mount_to"]]
    # USB device passthrough. Two boards (DUT + satellite) -> two --device maps.
    devs = device if isinstance(device, (list, tuple)) else ([device] if device else [])
    for d in devs:
        if d:
            cmd += ["--device", d]
    if devs:
        cmd += ["--group-add", "dialout"]
    # Egress control (full enforcement is the proxy/network from #7).
    if cfg["network"]:
        cmd += ["--network", cfg["network"]]
    if cfg["https_proxy"]:
        cmd += ["-e", "HTTPS_PROXY=" + cfg["https_proxy"],
                "-e", "HTTP_PROXY=" + cfg["https_proxy"]]
    cmd += [cfg["image"]]
    cmd += agent_argv
    return cmd


def container_state(cfg, runner):
    """'running', 'stopped', or 'absent' (best-effort; '' under dry-run)."""
    if runner.dry_run or not have("docker"):
        return ""
    rc, out = runner.run(["docker", "ps", "-a", "--filter",
                          "name=^" + cfg["container"] + "$",
                          "--format", "{{.State}}"])
    return out.strip()


def cmd_up(args, cfg, host_os, runner):
    if host_os != "windows" and not have("docker") and not args.dry_run:
        print("x docker not found. Run `mcuflow up doctor`.", file=sys.stderr)
        return EXIT_NOTOOL

    agent_argv = (args.agent or cfg["agent"]).split()

    # Resume an existing cage if present (workspace mount persists).
    state = container_state(cfg, runner)
    if state == "running" and not args.fresh:
        print("Resuming running cage '" + cfg["container"] + "' (exec agent):")
        return runner.run(["docker", "exec", "-it", cfg["container"]] + agent_argv,
                          interactive=True)[0]
    if state == "stopped" and not args.fresh:
        print("Resuming stopped cage '" + cfg["container"] + "':")
        return runner.run(["docker", "start", "-ai", cfg["container"]],
                          interactive=True)[0]

    # Fresh start. Collect one or more boards (DUT + satellite).
    devices = list(args.device or [])
    busids = list(args.busid or [])
    if host_os == "windows":
        if busids:
            for i, bid in enumerate(busids):
                print("Binding USB device " + bid + " into WSL2:")
                for step in windows_usb_steps(bid):
                    runner.run(step)
                # usbipd attaches devices into WSL in order; name them ttyACM0,1,...
                devices.append("/dev/ttyACM" + str(i))
        elif not devices:
            print("note: no --busid/--device given; starting cage without a board "
                  "(run `usbipd list` then pass --busid for each board).")
    elif host_os == "linux":
        if not devices:
            found = list_serial_host()
            devices = found[:2]  # DUT + satellite if both present
            for d in devices:
                print("auto-selected board: " + d)
    device = devices

    print("Starting fresh cage '" + cfg["container"] + "' (agent: "
          + " ".join(agent_argv) + "):")
    cmd = build_run_cmd(cfg, host_os, device, agent_argv, args.project)
    return runner.run(cmd, interactive=True)[0]


def cmd_down(args, cfg, host_os, runner):
    print("Stopping and removing cage '" + cfg["container"] + "':")
    runner.run(["docker", "rm", "-f", cfg["container"]])
    return EXIT_OK


# --- parsing ---------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="mcuflow up",
                                description="Launcher: open the cage, pass USB, seat the agent.")
    p.add_argument("--os", default="auto", choices=["auto", "linux", "windows", "macos"])
    p.add_argument("--dry-run", action="store_true", help="print commands without running")
    p.add_argument("--project", type=Path, default=Path("."), help="host project dir")
    p.add_argument("--image", default=None)
    p.add_argument("--name", default=None, help="container name")
    p.add_argument("--agent", default=None, help="agent command to run inside")
    sub = p.add_subparsers(dest="cmd")

    u = sub.add_parser("up", help="start or resume the cage (default)")
    u.add_argument("--device", action="append", default=None, help="serial device to pass through (repeat for DUT + satellite)")
    u.add_argument("--busid", action="append", default=None, help="(Windows) usbipd bus id to attach (repeat for two boards)")
    u.add_argument("--fresh", action="store_true", help="ignore any existing cage")
    u.set_defaults(func=cmd_up)

    dp = sub.add_parser("doctor", help="check prerequisites")
    dp.add_argument("--fix", action="store_true",
                    help="install missing cage prerequisites (usbipd-win, Docker) "
                         "and pull the ESP-IDF image before checking")
    dp.set_defaults(func=cmd_doctor)
    sub.add_parser("usb", help="list boards / passthrough plan").set_defaults(func=cmd_usb)
    sub.add_parser("down", help="stop and remove the cage").set_defaults(func=cmd_down)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    # Default subcommand is "up".
    if args.cmd is None:
        args.cmd = "up"
        args.func = cmd_up
        args.device = getattr(args, "device", None)
        args.busid = getattr(args, "busid", None)
        args.fresh = getattr(args, "fresh", False)

    cfg = load_config(args.project)
    if args.image:
        cfg["image"] = args.image
    if args.name:
        cfg["container"] = args.name

    host_os = detect_os(args.os)
    runner = Runner(args.dry_run)
    return args.func(args, cfg, host_os, runner)


if __name__ == "__main__":
    raise SystemExit(main())
