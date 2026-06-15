#!/usr/bin/env python3
"""
mcuflow - the deterministic conductor CLI for the micro-controller workflow.

This is the single canonical execution path (deliverable #2). It wraps the
modular deliverables as verbs with a stable contract:
  * human-readable output by default; one JSON object with --json
  * documented, stable exit codes
CI, scripts, and the agent all go through this, so behavior never diverges.

Verbs:
  validate <board.yml>             structure + semantic check        (#1)
  scaffold <board.yml> [-o dir]    generate an ESP-IDF project        (#3)
  build    [--path .]              build via the platform adapter    (or --sim)
  flash    [--path .] [--port P]   flash via the platform adapter    (or --sim)
  monitor  [--path .] [--port P]   serial monitor via the platform adapter
  test     <pyfile> [--target c]   pytest-embedded HIL run
  hil      <board.yml>             workbench-mediated HIL (sim or real)
  run      <board.yml> [-o dir]    validate->scaffold->build->flash->hil
  env doctor                       report toolchain availability

Global flags:
  --json    emit one JSON object instead of human text
  --sim     run build/flash/test against the simulator (no toolchain/hardware)

Exit codes (stable contract):
  0    success
  1    verb-level failure (invalid board, build/test failed)
  2    usage / bad input
  127  a required external tool (idf.py / pytest) is not installed
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # src/: the code root (board-schema/, sim/, ... live here)
REPO_ROOT = ROOT.parent  # the repository root (.venv, build-out/, cage.yaml live here)


def _augment_path():
    """Make freshly-installed tools findable without restarting the shell.

    winget installs (usbipd-win) update the *system* PATH, but an already-running
    shell keeps its old PATH, so `shutil.which` misses them. Prepend the known
    install dirs so the tool's own --fix run can see what it just installed.
    """
    extra = []
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        extra += [
            os.path.join(pf, "usbipd-win"),
            os.path.join(pf, "Docker", "Docker", "resources", "bin"),
        ]
    for d in extra:
        if d and os.path.isdir(d) and d not in os.environ.get("PATH", ""):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


_augment_path()


# --- project virtualenv (uv-managed) ---------------------------------------
# Python deps (pyyaml, jsonschema, pyserial, esptool) live in a project-local
# .venv created by uv - not in global site-packages. So that `python
# mcuflow/mcuflow.py ...` works no matter which interpreter launches it, the
# tool re-execs itself into the venv's interpreter when one exists.


def _venv_dir():
    return REPO_ROOT / ".venv"


def _venv_python(venv=None):
    venv = venv or _venv_dir()
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _same_path(a, b):
    """Path equality that survives 8.3 short names and case on Windows."""
    try:
        na = os.path.normcase(os.path.realpath(str(a)))
        nb = os.path.normcase(os.path.realpath(str(b)))
        return na == nb
    except Exception:
        return False


def _maybe_reexec_into_venv():
    if os.environ.get("MCUFLOW_NO_REEXEC") == "1":
        return
    # Uninstall deletes the .venv, so it must run under the launching interpreter,
    # not the venv python (which would be holding the directory open on Windows).
    if "--uninstall" in sys.argv:
        return
    vpy = _venv_python()
    if not vpy.exists() or _same_path(sys.executable, vpy):
        return
    # Re-run under the venv interpreter via subprocess (NOT os.execv): on Windows
    # os.execv does not replace the process - it spawns asynchronously and returns
    # control (exit 0) to the shell immediately, so the real work would run
    # detached with a bogus exit code. subprocess.run is synchronous, inherits
    # stdio, and propagates the true exit code on every platform.
    env = dict(os.environ)
    env["MCUFLOW_NO_REEXEC"] = "1"  # guard against loops
    proc = subprocess.run([str(vpy), os.path.abspath(__file__)] + sys.argv[1:], env=env)
    sys.exit(proc.returncode)


EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_NOTOOL = 127


def _validator_path() -> Path:
    return Path(os.environ.get("MCUFLOW_VALIDATOR", ROOT / "board-schema" / "validate.py"))


def _scaffold_path() -> Path:
    return Path(os.environ.get("MCUFLOW_SCAFFOLD", ROOT / "project-template" / "scaffold.py"))


def emit(result: dict, as_json: bool, human_lines=None) -> int:
    """Print either a JSON envelope or human lines; return the exit code."""
    if as_json:
        print(json.dumps(result))
    else:
        for line in human_lines or []:
            print(line)
    return int(result.get("exit_code", EXIT_OK))


def _run(cmd, capture=True, cwd=None):
    """Run a subprocess; return (rc, stdout, stderr)."""
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
    )
    return proc.returncode, (proc.stdout or ""), (proc.stderr or "")


def _need_tool(name, as_json):
    """Return an exit code if `name` is missing, else None."""
    if shutil.which(name) is None:
        result = {
            "verb": "env",
            "ok": False,
            "exit_code": EXIT_NOTOOL,
            "missing_tool": name,
            "detail": name + " not found on PATH. Run `mcuflow env doctor`.",
        }
        emit(
            result,
            as_json,
            [
                "x " + name + " is not installed / not on PATH.",
                "  This verb needs it. Try: mcuflow env doctor",
            ],
        )
        return EXIT_NOTOOL
    return None


def _read_board(path):
    """Best-effort load of board.yml for project name / rig info."""
    try:
        import yaml  # type: ignore

        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


# --- verbs -----------------------------------------------------------------


def verb_validate(args):
    tool = _validator_path()
    if not tool.exists():
        return emit(
            {
                "verb": "validate",
                "ok": False,
                "exit_code": EXIT_USAGE,
                "detail": "validator not found at " + str(tool),
            },
            args.json,
            ["x validator not found at " + str(tool)],
        )
    rc, out, err = _run([sys.executable, str(tool), str(args.board)])
    ok = rc == 0
    result = {
        "verb": "validate",
        "ok": ok,
        "exit_code": rc,
        "board": str(args.board),
        "detail": (out + err).strip(),
    }
    return emit(result, args.json, [(out + err).rstrip()])


def verb_scaffold(args):
    tool = _scaffold_path()
    if not tool.exists():
        return emit(
            {
                "verb": "scaffold",
                "ok": False,
                "exit_code": EXIT_USAGE,
                "detail": "scaffold tool not found at " + str(tool),
            },
            args.json,
            ["x scaffold tool not found at " + str(tool)],
        )
    cmd = [sys.executable, str(tool), str(args.board)]
    if args.out:
        cmd += ["-o", str(args.out)]
    rc, out, err = _run(cmd)
    ok = rc == 0
    result = {
        "verb": "scaffold",
        "ok": ok,
        "exit_code": rc,
        "board": str(args.board),
        "out": str(args.out) if args.out else None,
        "detail": (out + err).strip(),
    }
    return emit(result, args.json, [(out + err).rstrip()])


def _adapter(platform):
    """The PlatformAdapter for `platform` (defaults to esp32). The adapter maps
    build/flash/monitor to that toolchain's command argv; the conductor runs it.
    This is the seam that keeps the CLI from assuming a specific processor -
    adding a platform is a new adapter, not a CLI change (see src/adapters/)."""
    sys.path.insert(0, str(ROOT))
    from adapters import get_adapter

    return get_adapter(platform or "esp32")


def _run_verb(name, cmd, args, interactive=False):
    """Run a toolchain command (the argv a PlatformAdapter returned). cmd[0] is
    the required tool, so the missing-tool error is reported generically."""
    miss = _need_tool(cmd[0], args.json)
    if miss is not None:
        return miss
    if interactive:
        rc, out, err = _run(cmd, capture=False)
        return emit({"verb": name, "ok": rc == 0, "exit_code": rc}, args.json, [])
    rc, out, err = _run(cmd)
    ok = rc == 0
    return emit(
        {"verb": name, "ok": ok, "exit_code": rc, "detail": (out + err).strip()},
        args.json,
        [(out + err).rstrip()],
    )


def _sim_result(verb, lines, **extra):
    """A successful simulated step in the standard envelope."""
    res = {"verb": verb, "ok": True, "exit_code": EXIT_OK, "sim": True}
    res.update(extra)
    res["detail"] = "\n".join(lines)
    return res


# --- containerized toolchain (cage) ----------------------------------------
# When the native toolchain isn't on the host, a platform's adapter can build
# inside its cage image and/or flash from the host (for esp32: idf.py in the
# ESP-IDF image, esptool over the COM port). The conductor just runs the argv
# the adapter returns - the platform owns its toolchain/image.


def _cage_available(image):
    """True if the cage can run: docker is up and `image` is pulled."""
    if not image or shutil.which("docker") is None or not _docker_running():
        return False
    rc, out, _e = _run(["docker", "images", "-q", image])
    return rc == 0 and bool(out.strip())


def verb_build(args):
    if args.sim:
        lines = [
            "[sim] build ok (no toolchain invoked)",
            "  binary : build/app.bin  (simulated 0x31a20 bytes)",
            "  warnings: 0   target: from sdkconfig",
        ]
        return emit(_sim_result("build", lines, bin_bytes=203808, warnings=0), args.json, lines)
    platform = getattr(args, "platform", None) or "esp32"
    adapter = _adapter(platform)
    cmd = adapter.build_cmd(str(args.path))
    # Native toolchain on the host (idf.py for esp32; cmake/west/... for others).
    if shutil.which(cmd[0]) is not None:
        return _run_verb("build", cmd, args)
    # No host toolchain: build inside the platform's cage image if it has one.
    image = _cage_image(adapter)
    chip = getattr(args, "chip", None) or "esp32c3"
    cage_cmd = adapter.cage_build_cmd(str(args.path), chip, image)
    if cage_cmd is not None and _cage_available(image):
        rc, out, err = _run(cage_cmd)
        ok = rc == 0
        lines = ["[cage] build (" + image + ", target " + chip + ")", (out + err).rstrip()]
        return emit(
            {
                "verb": "build",
                "ok": ok,
                "exit_code": rc,
                "cage": True,
                "chip": chip,
                "detail": (out + err).strip(),
            },
            args.json,
            lines,
        )
    return _run_verb("build", cmd, args)  # emits the missing-tool error for cmd[0]


def verb_flash(args):
    if args.sim:
        port = args.port or "(sim)"
        lines = [
            "[sim] flash ok on port " + port,
            "  wrote app.bin @ 0x10000  (simulated)",
            "  hard-reset -> running",
        ]
        return emit(_sim_result("flash", lines, port=port), args.json, lines)
    platform = getattr(args, "platform", None) or "esp32"
    adapter = _adapter(platform)
    cmd = adapter.flash_cmd(str(args.path), getattr(args, "port", None))
    # Native toolchain on the host (idf.py for esp32; openocd/picotool/... else).
    if shutil.which(cmd[0]) is not None:
        return _run_verb("flash", cmd, args)
    # No host toolchain: flash already-built artifacts from the host if the
    # platform supports it (esp32: esptool over the COM port).
    chip = getattr(args, "chip", None) or "esp32c3"
    try:
        hf = adapter.host_flash_cmd(str(args.path), args.port, chip, sys.executable)
    except Exception as e:
        return emit(
            {"verb": "flash", "ok": False, "exit_code": EXIT_FAIL, "detail": str(e)},
            args.json,
            ["x " + str(e)],
        )
    if hf is None:
        return _run_verb("flash", cmd, args)  # unsupported -> missing-tool error for cmd[0]
    rc, out, err = _run(hf)
    ok = rc == 0
    lines = [
        "[host] flash (chip " + chip + ", port " + str(args.port) + ")",
        (out + err).rstrip(),
    ]
    return emit(
        {
            "verb": "flash",
            "ok": ok,
            "exit_code": rc,
            "host_flash": True,
            "chip": chip,
            "port": args.port,
            "detail": (out + err).strip(),
        },
        args.json,
        lines,
    )


def verb_monitor(args):
    platform = getattr(args, "platform", None) or "esp32"
    cmd = _adapter(platform).monitor_cmd(str(args.path), getattr(args, "port", None))
    return _run_verb("monitor", cmd, args, interactive=True)


def verb_test(args):
    if args.sim:
        # In sim, a bare `test` confirms the boot gate via the HIL harness.
        return verb_hil(args, board=args.pyfile)
    miss = _need_tool("pytest", args.json)
    if miss is not None:
        return miss
    cmd = ["pytest"]
    if args.target:
        cmd += ["--target", args.target]
    cmd += [str(args.pyfile)]
    rc, out, err = _run(cmd)
    ok = rc == 0
    return emit(
        {
            "verb": "test",
            "ok": ok,
            "exit_code": rc,
            "target": args.target,
            "detail": (out + err).strip(),
        },
        args.json,
        [(out + err).rstrip()],
    )


def verb_hil(args, board=None):
    """Workbench-mediated HIL run (sim by default; --workbench points at a real one)."""
    board = board or args.board
    sys.path.insert(0, str(ROOT))
    try:
        from sim.hil import run_hil
    except Exception as e:
        return emit(
            {
                "verb": "hil",
                "ok": False,
                "exit_code": EXIT_FAIL,
                "detail": "could not load sim harness: " + str(e),
            },
            args.json,
            ["x could not load sim harness: " + str(e)],
        )
    satellite = getattr(args, "satellite", "sim") or "sim"
    wb = getattr(args, "workbench", None)
    try:
        rep = run_hil(str(board), satellite=satellite, workbench_base=wb)
    except Exception as e:
        return emit(
            {
                "verb": "hil",
                "ok": False,
                "exit_code": EXIT_FAIL,
                "detail": "hil run failed: " + str(e),
            },
            args.json,
            ["x hil run failed: " + str(e)],
        )
    rc = EXIT_OK if rep["ok"] else EXIT_FAIL
    lines = [
        "HIL run ("
        + ("sim satellite" if satellite == "sim" else satellite)
        + ")  "
        + str(rep["passed"])
        + "/"
        + str(rep["total"])
        + " steps passed:"
    ]
    for s in rep["steps"]:
        lines.append(
            "  [" + ("PASS" if s["ok"] else "FAIL") + "] " + s["step"] + " - " + s["detail"]
        )
    if rep.get("serial_log"):
        lines.append("  device serial:")
        for ln in rep["serial_log"]:
            lines.append("    | " + ln)
    lines.append("RESULT: " + ("PASS" if rep["ok"] else "FAIL"))
    out = {"verb": "hil", "ok": rep["ok"], "exit_code": rc, "report": rep}
    return emit(out, args.json, lines)


def _autodetect_dut_satellite():
    """Detect connected boards -> (dut, satellite, n_boards, reason).

    Reuses the port viewer's logic so `run` and the viewer agree. dut/satellite
    may be None for a genuine no-board case (list_ports_info() returns [] when
    pyserial is absent). This does NOT swallow unexpected errors - a real failure
    raises so verb_run fails the ports stage loudly instead of masking it as
    "no board" and flashing the toolchain default.
    """
    pv = _load_sibling("mcuflow_portviewer", "portviewer/portviewer.py")
    ports = pv.list_ports_info()
    nboards = len(pv.boards(ports))
    mapping, reason = pv.suggest_roles(ports)
    dut, sat = pv.roles_to_ports(mapping)
    return dut, sat, nboards, reason


def verb_run(args):
    """End-to-end: validate -> scaffold -> build -> flash -> hil. Honors --sim.

    On real hardware (no --sim) with no explicit --port, the DUT port is
    auto-detected from the connected boards and the choice is narrated as a
    "ports" stage, so the automatic assignment is visible rather than silent.
    """
    stages = []

    def add(name, rc, detail):
        stages.append({"stage": name, "ok": rc == EXIT_OK, "exit_code": rc, "detail": detail})
        return rc

    def finish(code):
        passed = sum(1 for s in stages if s["ok"])
        out = {
            "verb": "run",
            "ok": code == EXIT_OK,
            "exit_code": code,
            "board": str(args.board),
            "sim": args.sim,
            "passed": passed,
            "total": len(stages),
            "stages": stages,
        }
        lines = [
            "mcuflow run "
            + ("[sim] " if args.sim else "")
            + str(args.board)
            + "  -> "
            + str(passed)
            + "/"
            + str(len(stages))
            + " stages ok:"
        ]
        for s in stages:
            head = "  [" + ("ok  " if s["ok"] else "FAIL") + "] " + s["stage"]
            lines.append(head)
            detail = (s["detail"] or "").strip().splitlines()
            # Show every line of the stage that decided the result, and of the
            # hil stage (its per-step PASS/FAIL + DUT serial is the whole point);
            # other passing stages get a short head so the summary stays scannable.
            show = detail if (not s["ok"] or s["stage"] in ("hil", "ports")) else detail[:3]
            for ln in show:
                lines.append("        " + ln)
        lines.append("RESULT: " + ("PASS" if code == EXIT_OK else "FAIL"))
        return emit(out, args.json, lines)

    # 0. ports - resolve the DUT (and note the satellite) from connected boards
    #    when running on real hardware without an explicit --port. Narrated as a
    #    stage so the automatic choice is visible, never silent.
    port = getattr(args, "port", None)
    if not args.sim:
        if port:
            add("ports", EXIT_OK, "using --port " + port + " for the DUT")
        else:
            try:
                dut, sat, nboards, reason = _autodetect_dut_satellite()
            except Exception as ex:
                add("ports", EXIT_FAIL, "port auto-detect failed: " + str(ex))
                return finish(EXIT_FAIL)
            if dut:
                port = dut
                detail = "auto-detected " + str(nboards) + " board(s): " + dut + " = DUT"
                if sat:
                    detail += ", " + sat + " = satellite"
                detail += "\nwhy: " + reason
                if sat and not getattr(args, "workbench", None):
                    detail += (
                        "\nsatellite found - start it with `mcuflow workbench --satellite "
                        + sat
                        + "`"
                    )
                add("ports", EXIT_OK, detail)
            else:
                add(
                    "ports",
                    EXIT_OK,
                    "no board auto-detected ("
                    + reason
                    + "); flashing will use the toolchain default - pass --port to pin it",
                )

    # 1. validate
    vt = _validator_path()
    rc, o, e = _run([sys.executable, str(vt), str(args.board)])
    add("validate", rc, (o + e).strip())
    if rc != EXIT_OK:
        return finish(EXIT_FAIL)

    # 2. scaffold
    board = _read_board(args.board)
    project = (board.get("meta") or {}).get("project", "project")
    out_dir = Path(args.out) if args.out else (REPO_ROOT / "build-out" / project)
    st = _scaffold_path()
    rc, o, e = _run([sys.executable, str(st), str(args.board), "-o", str(out_dir)])
    add("scaffold", rc, (o + e).strip())
    if rc != EXIT_OK:
        return finish(EXIT_FAIL)

    platform = (board.get("meta") or {}).get("platform") or "esp32"
    chip = (board.get("meta") or {}).get("chip") or "esp32c3"
    adapter = _adapter(platform)

    # 3. build  (native toolchain via the adapter; else the platform's cage image).
    build_cmd = adapter.build_cmd(str(out_dir))
    image = _cage_image(adapter)
    cage_cmd = adapter.cage_build_cmd(str(out_dir), chip, image)
    if args.sim:
        add("build", EXIT_OK, "[sim] build ok")
    elif shutil.which(build_cmd[0]) is not None:
        rc, o, e = _run(build_cmd)
        add("build", rc, (o + e).strip())
        if rc != EXIT_OK:
            return finish(EXIT_FAIL)
    elif cage_cmd is not None and _cage_available(image):
        rc, o, e = _run(cage_cmd)
        add("build", rc, "[cage " + chip + "] " + (o + e).strip())
        if rc != EXIT_OK:
            return finish(EXIT_FAIL)
    else:
        add(
            "build",
            EXIT_NOTOOL,
            "no " + build_cmd[0] + " toolchain (run `mcuflow doctor --fix`, or use --sim)",
        )
        return finish(EXIT_NOTOOL)

    # 4. flash  (native toolchain via the adapter; else the platform's host flash).
    #    `port` was resolved in the ports stage above (explicit --port or auto).
    flash_cmd = adapter.flash_cmd(str(out_dir), port)
    if args.sim:
        add("flash", EXIT_OK, "[sim] flash ok")
    elif shutil.which(flash_cmd[0]) is not None:
        rc, o, e = _run(flash_cmd)
        add("flash", rc, (o + e).strip())
        if rc != EXIT_OK:
            return finish(EXIT_FAIL)
    else:
        try:
            hf = adapter.host_flash_cmd(str(out_dir), port, chip, sys.executable)
        except Exception as e:
            add("flash", EXIT_FAIL, str(e))
            return finish(EXIT_FAIL)
        if hf is None:
            add("flash", EXIT_NOTOOL, "no " + flash_cmd[0] + " on PATH for flashing")
            return finish(EXIT_NOTOOL)
        rc, o, e = _run(hf)
        add("flash", rc, "[host flash] " + (o + e).strip())
        if rc != EXIT_OK:
            return finish(EXIT_FAIL)

    # 5. hil (workbench-mediated). sim by default; real needs --workbench.
    needs_sat = (board.get("rig") or {}).get("satellite") == "required" or "wifi" in (
        (board.get("test") or {}).get("needs") or []
    )
    if args.sim or needs_sat:
        sys.path.insert(0, str(ROOT))
        try:
            from sim.hil import run_hil

            satellite = "sim" if args.sim else (getattr(args, "satellite", None) or "sim")
            wb = getattr(args, "workbench", None)
            # Real run (not --sim, real workbench, a DUT port): assert against the
            # actual DUT serial instead of the modelled SimDUT.
            dut_port = None if args.sim else (port if wb else None)
            rep = run_hil(
                str(args.board), satellite=satellite, workbench_base=wb, dut_port=dut_port
            )
            detail = "\n".join(
                "[" + ("PASS" if s["ok"] else "FAIL") + "] " + s["step"] + " - " + s["detail"]
                for s in rep["steps"]
            )
            for ln in (rep.get("serial_log") or [])[-8:]:
                detail += "\n   | " + ln
            add("hil", EXIT_OK if rep["ok"] else EXIT_FAIL, detail)
            if not rep["ok"]:
                return finish(EXIT_FAIL)
        except Exception as ex:
            add("hil", EXIT_FAIL, "hil error: " + str(ex))
            return finish(EXIT_FAIL)

    return finish(EXIT_OK)


def _load_sibling(modname, relpath):
    import importlib.util

    spec = importlib.util.spec_from_file_location(modname, str(ROOT / relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verb_up(args):
    """Delegate to the launcher (deliverable #4): open the cage, pass USB."""
    up = _load_sibling("mcuflow_launcher", "launcher/up.py")
    return up.main(args.rest)


def verb_workbench(args):
    """Delegate to the workbench service (deliverable #9)."""
    wb = _load_sibling("mcuflow_workbench", "workbench/workbench.py")
    return wb.main(args.rest)


def verb_ports(args):
    """Delegate to the COM-port viewer (GUI/text/JSON).

    The global --json flag makes this print a structured snapshot (what the VS
    Code extension's Boards tree consumes); it takes precedence over the GUI.
    """
    pv = _load_sibling("mcuflow_portviewer", "portviewer/portviewer.py")
    if args.json:
        return pv.main(["--json"])
    fwd = (["--list"] if args.list else []) + (["--watch"] if args.watch else [])
    return pv.main(fwd)


def verb_bridge(args):
    """Delegate to the RFC2217 serial bridge (share a port over the network)."""
    sb = _load_sibling("mcuflow_serialbridge", "serialbridge/serialbridge.py")
    return sb.main(["--port", args.port, "--tcp", str(args.tcp)])


def verb_debug(args):
    """Delegate to the OpenOCD GDB-server launcher (JTAG/debug)."""
    dbg = _load_sibling("mcuflow_debugger", "debugger/debugger.py")
    fwd = ["--chip", args.chip] + (["--board", args.board] if args.board else [])
    return dbg.main(fwd)


def _list_serial_ports():
    """Device names of connected serial ports.

    Delegates to the port viewer's enumerator so doctor and `mcuflow ports` give
    the same answer (one source of truth), with a POSIX glob fallback for the
    case where pyserial isn't importable yet (e.g. before `doctor --fix`).
    """
    pv = _load_sibling("mcuflow_portviewer", "portviewer/portviewer.py")
    ports = [p["device"] for p in pv.list_ports_info()]
    if not ports and os.name != "nt":
        import glob

        ports = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    return ports


def _have_module(name):
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


# --- self-install (doctor --fix) -------------------------------------------
# The tool installs its OWN prerequisites so a fresh machine goes green with one
# command. Each installer returns (ok, log_line). Nothing here needs the caller
# to hand-install anything; pip/winget/docker do the work.

# The Python deps the tool needs (declared in pyproject.toml; this map is only
# for the doctor status display).  import-name -> distribution name.
_PY_DEPS = {
    "yaml": "pyyaml",
    "jsonschema": "jsonschema",
    "serial": "pyserial",
    "esptool": "esptool",
}

# host tool -> winget package id (Windows only).
_WINGET_IDS = {"usbipd": "dorssel.usbipd-win", "docker": "Docker.DockerDesktop"}


def _ensure_uv():
    """Return (uv_argv, log_line). Install uv if it is missing."""
    if shutil.which("uv"):
        return ["uv"], "uv: already present"
    rc, out, err = _run([sys.executable, "-m", "pip", "install", "--upgrade", "uv"])
    if rc != 0:
        return None, "uv install FAILED\n" + (out + err).strip()
    if shutil.which("uv"):
        return ["uv"], "uv: installed"
    return [sys.executable, "-m", "uv"], "uv: installed (module)"


def _ensure_venv(uv_argv):
    vdir = _venv_dir()
    vpy = _venv_python(vdir)
    if vpy.exists():
        return True, "venv: present (" + str(vdir) + ")"
    rc, out, err = _run(uv_argv + ["venv", str(vdir)])
    if rc == 0 and vpy.exists():
        return True, "venv: created (" + str(vdir) + ")"
    return False, "venv create FAILED\n" + (out + err).strip()


def _uv_install_project(uv_argv):
    """Editable-install the project (and its declared dependencies) into the
    .venv. pyproject.toml is the single source of truth for the deps, and this
    also creates the `mcuflow` console script."""
    vpy = _venv_python()
    cmd = uv_argv + ["pip", "install", "--python", str(vpy), "-e", str(REPO_ROOT)]
    rc, out, err = _run(cmd)
    return rc == 0, (
        "uv pip install -e . -> .venv: " + ("ok" if rc == 0 else "FAILED\n" + (out + err).strip())
    )


def _module_status(names):
    """Whether each module is importable in the *venv* (the canonical env) if it
    exists, else in the current interpreter."""
    vpy = _venv_python()
    try:
        in_venv = Path(sys.executable).resolve() == vpy.resolve()
    except Exception:
        in_venv = False
    if vpy.exists() and not in_venv:
        code = (
            "import importlib.util,json;"
            "print(json.dumps({m: importlib.util.find_spec(m) is not None "
            "for m in " + repr(list(names)) + "}))"
        )
        rc, out, _e = _run([str(vpy), "-c", code])
        if rc == 0 and out.strip():
            try:
                return json.loads(out.strip().splitlines()[-1])
            except Exception:
                pass
    return {m: _have_module(m) for m in names}


def _winget_install(pkg_id):
    if shutil.which("winget") is None:
        return False, "winget not on PATH; cannot auto-install " + pkg_id
    cmd = [
        "winget",
        "install",
        "--id",
        pkg_id,
        "-e",
        "--silent",
        "--accept-source-agreements",
        "--accept-package-agreements",
        "--disable-interactivity",
    ]
    rc, out, err = _run(cmd)
    blob = out + err
    # winget returns non-zero when the package is already installed; treat that
    # (and "no applicable upgrade") as success so --fix is idempotent.
    already = "already installed" in blob.lower() or "no available upgrade" in blob.lower()
    ok = rc == 0 or already
    return ok, ("winget " + pkg_id + ": " + ("ok" if ok else "FAILED\n" + blob.strip()))


def _docker_running():
    if shutil.which("docker") is None:
        return False
    rc, _o, _e = _run(["docker", "info"])
    return rc == 0


def _ensure_docker_running(timeout_s=180):
    """Start the Docker engine if it's installed but stopped; wait until ready."""
    if shutil.which("docker") is None:
        return False, "docker not present"
    if _docker_running():
        return True, "docker engine: already running"
    # Launch Docker Desktop (Windows) or start the service (Linux).
    if os.name == "nt":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Docker\Docker\Docker Desktop.exe"),
            os.path.expandvars(r"%ProgramW6432%\Docker\Docker\Docker Desktop.exe"),
        ]
        exe = next((c for c in candidates if os.path.exists(c)), None)
        if exe:
            try:
                subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                return False, "docker engine: could not launch Desktop (" + str(e) + ")"
        else:
            return False, "docker engine: Docker Desktop.exe not found"
    else:
        _run(["systemctl", "start", "docker"])
    import time

    waited = 0
    while waited < timeout_s:
        if _docker_running():
            return True, "docker engine: started (waited " + str(waited) + "s)"
        time.sleep(5)
        waited += 5
    return False, (
        "docker engine: not ready after "
        + str(timeout_s)
        + "s (start Docker Desktop manually, then re-run --fix)"
    )


def _docker_pull(image):
    if shutil.which("docker") is None:
        return False, "docker not present; skipping image pull (" + image + ")"
    if not _docker_running():
        return False, (
            "docker engine not running; skipping image pull ("
            + image
            + "). Start Docker Desktop and re-run `mcuflow doctor --fix`."
        )
    rc, out, err = _run(["docker", "pull", image])
    return rc == 0, (
        "docker pull " + image + ": " + ("ok" if rc == 0 else "FAILED\n" + (out + err).strip())
    )


def _cage_image(adapter=None):
    """The platform's headless toolchain image. Defaults to the adapter's
    `cage_image` (the platform owns it), with a cage.yaml `image:` override."""
    if adapter is None:
        adapter = _adapter("esp32")
    img = adapter.cage_image
    try:
        import yaml  # type: ignore

        data = yaml.safe_load((REPO_ROOT / "cage.yaml").read_text(encoding="utf-8")) or {}
        img = data.get("image") or img
    except Exception:
        pass
    return img


def _doctor_fix(host_is_windows):
    """Install everything the tool needs; return a list of log lines."""
    log = []

    # 1. Editable-install the project into a uv-managed .venv (not global
    #    site-packages). Deps come from pyproject.toml (pyyaml, jsonschema,
    #    pyserial, esptool - the last so the host can flash boards over their COM
    #    port without a native ESP-IDF install), and this also creates the
    #    `mcuflow` console script. mcuflow re-execs into this .venv on every run.
    uv_argv, line = _ensure_uv()
    log.append(line)
    if uv_argv:
        ok, line = _ensure_venv(uv_argv)
        log.append(line)
        if ok:
            ok, line = _uv_install_project(uv_argv)
            log.append(line)
    else:
        log.append("python deps: skipped (uv unavailable)")

    # 2. usbipd-win (Windows only; needed to pass USB into WSL2 for the cage).
    if host_is_windows and shutil.which("usbipd") is None:
        ok, line = _winget_install(_WINGET_IDS["usbipd"])
        log.append(line)
    elif host_is_windows:
        log.append("usbipd: already present")

    # 3. Docker (install only if missing; on Windows this is Docker Desktop).
    if shutil.which("docker") is None:
        if host_is_windows:
            ok, line = _winget_install(_WINGET_IDS["docker"])
            log.append(line + "  (a reboot/WSL2 start may be needed before first cage)")
        else:
            log.append(
                "docker missing: install via your package manager "
                "(e.g. `apt install docker.io` or Docker Desktop)"
            )
    else:
        log.append("docker: already present")

    # 4. Make sure the Docker engine is actually up (Desktop is often installed
    #    but not started), then pull the ESP-IDF cage image so build/flash works
    #    without a host toolchain.
    if shutil.which("docker") is not None:
        ok, line = _ensure_docker_running()
        log.append(line)
    img = _cage_image()
    ok, line = _docker_pull(img)
    log.append(line)

    return log


def _rm_path(path):
    """Remove a file or directory tree; return a log line."""
    import shutil as _sh

    p = Path(path)
    rel = str(p)
    if not p.exists():
        return rel + ": not present"
    try:
        if p.is_dir():
            _sh.rmtree(p)
        else:
            p.unlink()
        return "removed " + rel
    except Exception as e:
        return "could NOT remove " + rel + ": " + str(e)


def _doctor_uninstall(purge, host_is_windows):
    """Reverse what `doctor --fix` created. Returns a list of log lines.

    Default removes only project-local, regenerable things (the .venv, build
    artifacts, the cage container). --purge additionally removes the ~15GB cage
    image and (Windows) usbipd-win. Docker Desktop and uv are never touched -
    they pre-existed the install."""
    log = []

    # 1. The cage container (if any).
    if shutil.which("docker") is not None:
        rc, out, _e = _run(["docker", "rm", "-f", "mcuflow-cage"])
        log.append(
            "cage container 'mcuflow-cage': "
            + ("removed" if rc == 0 and out.strip() else "not present")
        )

    # 2. The uv-managed .venv - but not if we are running from it.
    if _same_path(sys.executable, _venv_python()):
        log.append(
            ".venv: SKIPPED - mcuflow is running from it. Re-run with the "
            "system python: `python mcuflow/mcuflow.py doctor --uninstall`"
        )
    else:
        log.append(_rm_path(_venv_dir()))

    # 3. Build artifacts (all regenerable).
    log.append(_rm_path(REPO_ROOT / "build-out"))
    for rel in (
        "satellite/firmware-idf/build",
        "satellite/firmware-idf/managed_components",
        "satellite/firmware-idf/dependencies.lock",
        "satellite/firmware-idf/sdkconfig",
    ):
        log.append(_rm_path(ROOT / rel))

    # 4. --purge: the big image and the system USB tool.
    img = _cage_image()
    if purge:
        if shutil.which("docker") is not None:
            rc, out, err = _run(["docker", "rmi", img])
            log.append(
                "cage image "
                + img
                + ": "
                + (
                    "removed (~15GB reclaimed)"
                    if rc == 0
                    else "not removed (" + (out + err).strip().splitlines()[-1] + ")"
                    if (out + err).strip()
                    else "not present"
                )
            )
        if host_is_windows and shutil.which("usbipd") is not None:
            rc, out, err = _run(
                [
                    "winget",
                    "uninstall",
                    "--id",
                    _WINGET_IDS["usbipd"],
                    "-e",
                    "--silent",
                    "--disable-interactivity",
                    "--accept-source-agreements",
                ]
            )
            log.append(
                "usbipd-win: "
                + (
                    "uninstalled"
                    if rc == 0
                    else "uninstall may need an elevation prompt - approve it"
                )
            )
    else:
        kept = "the " + img + " image (~15GB)"
        if host_is_windows:
            kept += " and usbipd-win"
        log.append("kept (re-run with --purge to remove): " + kept)

    log.append("left untouched: Docker Desktop and uv (they pre-existed --fix).")
    return log


def verb_doctor(args):
    """Preflight for a real two-board run: deps, toolchain, ports, satellite.

    With --fix the tool installs its own prerequisites first (a uv-managed .venv
    with the Python deps, usbipd-win, Docker if missing, and the ESP-IDF cage
    image), then re-checks and reports. With --uninstall it reverses that.
    """
    if getattr(args, "uninstall", False):
        ulog = _doctor_uninstall(
            purge=getattr(args, "purge", False), host_is_windows=(os.name == "nt")
        )
        lines = [
            "mcuflow doctor --uninstall"
            + (" --purge" if getattr(args, "purge", False) else "")
            + ":"
        ]
        lines += ["  " + ln for ln in ulog]
        return emit(
            {
                "verb": "doctor",
                "action": "uninstall",
                "ok": True,
                "exit_code": EXIT_OK,
                "purge": getattr(args, "purge", False),
                "log": ulog,
            },
            args.json,
            lines,
        )

    fix_log = []
    if getattr(args, "fix", False):
        fix_log = _doctor_fix(host_is_windows=(os.name == "nt"))

    # Toolchain binaries to check: the platform adapter names its own (esp32 ->
    # idf.py/esptool), plus the generic ones every platform shares.
    platform_tools = list(_adapter("esp32").toolchain_tools)
    tools = {
        t: shutil.which(t) for t in platform_tools + ["pytest", "cmake", "ninja", "git", "docker"]
    }
    # Python deps (incl. esptool) live in the .venv - check there, not just PATH.
    mods = _module_status(["yaml", "jsonschema", "serial", "esptool"])
    ports = _list_serial_ports()

    sat = None
    if getattr(args, "satellite", None):
        sys.path.insert(0, str(ROOT))
        try:
            from satellite.host.satellite_driver import Satellite

            if args.satellite == "sim":
                from satellite.host.sim import SimSatelliteTransport

                s = Satellite(SimSatelliteTransport())
            else:
                s = Satellite.open_serial(args.satellite)
            sat = s.ping()
        except Exception as e:
            sat = {"ok": False, "error": str(e)}

    core_ok = mods["yaml"] and mods["jsonschema"]
    sat_ok = (sat is None) or bool(sat.get("ok"))
    code = EXIT_OK if (core_ok and sat_ok) else EXIT_FAIL

    lines = ["mcuflow doctor:"]
    if fix_log:
        lines.append("  self-install (--fix):")
        for ln in fix_log:
            for sub in ln.splitlines():
                lines.append("    " + sub)
    lines.append("  python deps:")
    for m in ("yaml", "jsonschema"):
        lines.append(
            "    ["
            + ("ok " if mods[m] else "-- ")
            + "] "
            + m
            + ("" if mods[m] else "  (run: mcuflow doctor --fix)")
        )
    lines.append(
        "    ["
        + ("ok " if mods["serial"] else "-- ")
        + "] pyserial"
        + ("" if mods["serial"] else "  (needed for real serial / COM discovery)")
    )
    lines.append(
        "    ["
        + ("ok " if mods.get("esptool") else "-- ")
        + "] esptool"
        + (" (.venv)" if mods.get("esptool") else "  (host flashing)")
    )
    lines.append("  build toolchain:")
    for t in ("idf.py", "cmake", "ninja"):
        lines.append(
            "    ["
            + ("ok " if tools[t] else "-- ")
            + "] "
            + t
            + (("  " + tools[t]) if tools[t] else "  (missing)")
        )
    if not tools["idf.py"]:
        lines.append(
            "    note: no native ESP-IDF - use the cage: "
            + ("docker present" if tools["docker"] else "docker NOT found")
        )
    lines.append("  serial ports (" + str(len(ports)) + "):")
    for prt in ports:
        lines.append("    - " + prt)
    if not ports:
        lines.append(
            "    (none - plug the boards in; on Windows install pyserial "
            "and check Device Manager / `usbipd list`)"
        )
    if sat is not None:
        lines.append(
            "  satellite ("
            + str(args.satellite)
            + "): "
            + ("ok " + json.dumps(sat) if sat.get("ok") else "FAIL " + json.dumps(sat))
        )
    if code != EXIT_OK and not getattr(args, "fix", False):
        lines.append(
            "hint: run `mcuflow doctor --fix` to let the tool install "
            "the missing prerequisites for you."
        )
    lines.append("readiness: " + ("ok" if code == EXIT_OK else "issues above"))

    return emit(
        {
            "verb": "doctor",
            "ok": code == EXIT_OK,
            "exit_code": code,
            "tools": tools,
            "modules": mods,
            "ports": ports,
            "satellite": sat,
            "fix_log": fix_log,
        },
        args.json,
        lines,
    )


def verb_env(args):
    if args.action != "doctor":
        return emit(
            {
                "verb": "env",
                "ok": False,
                "exit_code": EXIT_USAGE,
                "detail": "unknown env action: " + str(args.action),
            },
            args.json,
            ["x unknown env action: " + str(args.action)],
        )
    tools = ["idf.py", "esptool.py", "esptool", "pytest", "python3", "git", "cmake", "ninja"]
    found = {t: shutil.which(t) for t in tools}
    ok = bool(found["idf.py"])
    lines = ["Toolchain check:"]
    for t in tools:
        mark = "ok " if found[t] else "-- "
        lines.append("  [" + mark + "] " + t + (("  " + found[t]) if found[t] else "  (missing)"))
    lines.append("build-ready: " + ("yes" if ok else "no (idf.py missing)"))
    lines.append("note: `--sim` runs build/flash/test with no toolchain at all.")
    return emit(
        {"verb": "env", "ok": ok, "exit_code": EXIT_OK, "tools": found, "build_ready": ok},
        args.json,
        lines,
    )


# --- argument parsing ------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(
        prog="mcuflow", description="Deterministic conductor for the micro-controller workflow."
    )
    p.add_argument("--json", action="store_true", help="emit one JSON object instead of human text")
    p.add_argument(
        "--sim",
        action="store_true",
        help="simulate build/flash/test (no toolchain or hardware needed)",
    )
    sub = p.add_subparsers(dest="verb", required=True)

    v = sub.add_parser("validate", help="check a board.yml")
    v.add_argument("board", type=Path)
    v.set_defaults(func=verb_validate)

    s = sub.add_parser("scaffold", help="generate an ESP-IDF project")
    s.add_argument("board", type=Path)
    s.add_argument("-o", "--out", type=Path, default=None)
    s.set_defaults(func=verb_scaffold)

    b = sub.add_parser("build", help="build via the platform adapter (or cage, or --sim)")
    b.add_argument("--path", type=Path, default=Path("."))
    b.add_argument("--platform", default=None, help="toolchain adapter (default esp32)")
    b.add_argument("--chip", default=None, help="target chip for a cage build (default esp32c3)")
    b.set_defaults(func=verb_build)

    f = sub.add_parser("flash", help="flash via the platform adapter (or host esptool, or --sim)")
    f.add_argument("--path", type=Path, default=Path("."))
    f.add_argument("--port", default=None)
    f.add_argument("--platform", default=None, help="toolchain adapter (default esp32)")
    f.add_argument(
        "--chip", default=None, help="target chip for host esptool flashing (default esp32c3)"
    )
    f.set_defaults(func=verb_flash)

    m = sub.add_parser("monitor", help="serial monitor via the platform adapter (interactive)")
    m.add_argument("--path", type=Path, default=Path("."))
    m.add_argument("--port", default=None)
    m.add_argument("--platform", default=None, help="toolchain adapter (default esp32)")
    m.set_defaults(func=verb_monitor)

    t = sub.add_parser("test", help="pytest-embedded HIL run (or --sim)")
    t.add_argument("pyfile", type=Path, help="pytest file, or board.yml with --sim")
    t.add_argument("--target", default=None)
    t.set_defaults(func=verb_test)

    h = sub.add_parser("hil", help="workbench-mediated HIL (sim or real)")
    h.add_argument("board", type=Path)
    h.add_argument("--satellite", default="sim", help="'sim' or a serial port for a real satellite")
    h.add_argument(
        "--workbench", default=None, help="base URL of a running workbench (real hardware)"
    )
    h.set_defaults(func=verb_hil)

    r = sub.add_parser("run", help="validate->scaffold->build->flash->hil")
    r.add_argument("board", type=Path)
    r.add_argument("-o", "--out", type=Path, default=None)
    r.add_argument("--port", default=None)
    r.add_argument("--satellite", default="sim")
    r.add_argument("--workbench", default=None)
    r.set_defaults(func=verb_run)

    up = sub.add_parser("up", help="open the cage / pass USB (launcher)")
    up.add_argument("rest", nargs=argparse.REMAINDER, help="args passed through to the launcher")
    up.set_defaults(func=verb_up)

    wbp = sub.add_parser("workbench", help="run the networked test instrument")
    wbp.add_argument(
        "rest", nargs=argparse.REMAINDER, help="args passed through to the workbench service"
    )
    wbp.set_defaults(func=verb_workbench)

    pv = sub.add_parser("ports", help="view connected boards / COM-port mapping (GUI)")
    pv.add_argument("--list", action="store_true", help="print the view once as text (no window)")
    pv.add_argument("--watch", action="store_true", help="open hidden; pop up when a board appears")
    pv.set_defaults(func=verb_ports)

    br = sub.add_parser("bridge", help="serve a serial port over the network (RFC2217)")
    br.add_argument("--port", required=True, help="local serial port to share (e.g. COM6)")
    br.add_argument("--tcp", type=int, default=4000, help="TCP port to listen on (default 4000)")
    br.set_defaults(func=verb_bridge)

    dbg = sub.add_parser("debug", help="start an OpenOCD GDB server (JTAG, built-in USB-JTAG)")
    dbg.add_argument("--chip", default="esp32c3", help="target chip (default esp32c3)")
    dbg.add_argument("--board", default=None, help="OpenOCD board config (overrides --chip)")
    dbg.set_defaults(func=verb_debug)

    d = sub.add_parser("doctor", help="preflight: deps, toolchain, ports, satellite")
    d.add_argument("--satellite", default=None, help="ping a satellite: 'sim' or a serial port")
    d.add_argument(
        "--fix",
        action="store_true",
        help="install missing prerequisites (uv .venv deps, usbipd-win, "
        "Docker if absent, ESP-IDF cage image) before checking",
    )
    d.add_argument(
        "--uninstall",
        action="store_true",
        help="reverse --fix: remove the .venv, build artifacts, and the "
        "cage container (add --purge for the image + usbipd-win)",
    )
    d.add_argument(
        "--purge",
        action="store_true",
        help="with --uninstall: also remove the ~15GB cage image and "
        "usbipd-win (never removes Docker Desktop or uv)",
    )
    d.set_defaults(func=verb_doctor)

    e = sub.add_parser("env", help="environment helpers")
    e.add_argument("action", choices=["doctor"])
    e.set_defaults(func=verb_env)

    return p


def _global_flag_strings(parser):
    """Top-level (pre-subcommand) option strings, e.g. {'--json', '--sim'}.

    Derived from the parser so the passthrough skip-set below can't drift from
    the real globals - add a global to build_parser() and this updates with it.
    """
    flags = set()
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction) or a.dest == "help":
            continue
        flags.update(a.option_strings)
    return flags


def main(argv=None):
    # Run under the project's uv-managed .venv if one exists (re-execs once).
    _maybe_reexec_into_venv()
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    # Delegate wrapped tools before argparse, so their own flags pass through
    # cleanly (e.g. `mcuflow workbench --satellite sim`, `mcuflow up --dry-run`).
    # Skip any leading global flags first (derived from the parser, so the set
    # can't drift) so this also fires for `mcuflow --sim up ...`; argparse's
    # REMAINDER would otherwise drop the leading passthrough option (bpo-17050).
    passthrough = {
        "up": ("mcuflow_launcher", "launcher/up.py"),
        "workbench": ("mcuflow_workbench", "workbench/workbench.py"),
    }
    globals_ = _global_flag_strings(parser)
    i = 0
    while i < len(argv) and argv[i] in globals_:
        i += 1
    if i < len(argv) and argv[i] in passthrough:
        mod, rel = passthrough[argv[i]]
        return _load_sibling(mod, rel).main(argv[i + 1 :])
    args = parser.parse_args(argv)
    if not hasattr(args, "sim"):
        args.sim = False
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
