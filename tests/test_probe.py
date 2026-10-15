"""Regression for `mcuflow commission --probe`: the board.yml-generated probe image.

The probe image is ESP-IDF C that runs on the DUT and prints one
`MCUFLOW-PROBE {json}` line per finding. These tests cover the generator (what
it probes and what it leaves unverified), the parser, and the checks built on
the result - each against a simulated bench that has the declared devices
(must PASS) and one that does not (must FAIL). Whether the generated C compiles
is checked separately in the ESP-IDF cage; whether it runs is a hardware step.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from commission import probe_fw  # noqa: E402
from sim.bench import SimBench  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "mcuflow_commission_probe_test", ROOT / "src" / "commission" / "commission.py"
)
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)

MCUFLOW = [sys.executable, str(ROOT / "src" / "mcuflow" / "mcuflow.py")]
C3_PATH = ROOT / "examples" / "board-c3.yml"
C3 = yaml.safe_load(C3_PATH.read_text(encoding="utf-8"))
FULL = yaml.safe_load((ROOT / "examples" / "board.yml").read_text(encoding="utf-8"))


def statuses(rep):
    return {c["check"]: c["status"] for c in rep["checks"]}


def detail(rep, name):
    return next(c["detail"] for c in rep["checks"] if c["check"] == name)


# --- what the probe image covers -----------------------------------------------


def test_plan_probes_the_c3_bme280_and_leaves_the_led_unverified():
    plan = probe_fw.probe_plan(C3)
    assert plan["i2c"] == [
        {
            "bus": "i2c0",
            "sda": 5,
            "scl": 6,
            "devices": [{"name": "temp", "part": "BME280", "addr": 0x76}],
        }
    ]
    unprobed = dict(plan["unprobed"])
    assert set(unprobed) == {"pins.status_led"}
    assert "GPIO" in unprobed["pins.status_led"]


def test_plan_on_the_full_example_names_every_unprobed_item_with_a_reason():
    plan = probe_fw.probe_plan(FULL)
    assert [b["bus"] for b in plan["i2c"]] == ["i2c0"]
    assert [d["addr"] for d in plan["i2c"][0]["devices"]] == [0x76, 0x3C]
    unprobed = dict(plan["unprobed"])
    assert set(unprobed) == {
        "pins.spi2",
        "pins.uart0",
        "pins.status_led",
        "devices.sd_card",
        "devices.motor",
    }
    assert all(reason for reason in unprobed.values())


def test_generated_main_c_probes_each_declared_address():
    src = probe_fw.gen_main_c(C3)
    assert 'probe_i2c_bus("i2c0", 5, 6,' in src
    assert "118" in src  # 0x76
    assert "i2c_master_probe" in src
    assert 'MCUFLOW-PROBE {"kind":"done"}' in src or '\\"kind\\":\\"done\\"' in src


def test_written_project_is_a_buildable_layout(tmp_path):
    probe_fw.write_project(C3, tmp_path)
    assert "project(" in (tmp_path / "CMakeLists.txt").read_text(encoding="utf-8")
    main_cmake = (tmp_path / "main" / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "esp_driver_i2c" in main_cmake and "esp_driver_gpio" in main_cmake
    sdk = (tmp_path / "sdkconfig.defaults").read_text(encoding="utf-8")
    assert "CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y" in sdk
    assert "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y" in sdk
    assert (tmp_path / "main" / "main.c").exists()


def test_fingerprint_follows_what_is_probed():
    a = probe_fw.fingerprint(C3)
    assert a == probe_fw.fingerprint(json.loads(json.dumps(C3)))
    moved = json.loads(json.dumps(C3))
    moved["devices"]["temp"]["address"] = 0x77
    assert probe_fw.fingerprint(moved) != a


def test_parse_skips_boot_noise_and_keeps_findings():
    lines = [
        "ESP-ROM:esp32c3-api1-20210207",
        "I (25) boot: ESP-IDF v6.0 2nd stage bootloader",
        'MCUFLOW-PROBE {"kind":"start","fw":"' + probe_fw.PROBE_FW + '"}',
        'garbage MCUFLOW-PROBE {"kind":"i2c_device","bus":"i2c0","device":"temp",'
        '"addr":118,"result":"ack"}',
        "MCUFLOW-PROBE {not json",
        'MCUFLOW-PROBE {"kind":"done"}',
    ]
    found = probe_fw.parse(lines)
    assert [f["kind"] for f in found] == ["start", "i2c_device", "done"]


# --- the checks against a simulated bench ---------------------------------------


def test_probe_passes_when_the_declared_device_answers():
    bench = SimBench(C3, probe=True)
    rep = cm.commission(C3, bench)
    st = statuses(rep)
    assert st["device:temp"] == "pass", detail(rep, "device:temp")
    assert "0x76" in detail(rep, "device:temp")
    assert st["pins:status_led"] == "unverified"
    assert "pins_devices" not in st  # replaced by per-item results
    assert rep["ok"]
    assert bench.probe_runs == 1


def test_probe_fails_when_the_device_is_absent():
    rep = cm.commission(C3, SimBench(C3, probe=True, i2c_present={}))
    assert statuses(rep)["device:temp"] == "fail"
    assert "found nothing" in detail(rep, "device:temp")
    assert not rep["ok"]


def test_probe_names_the_address_it_did_find():
    # The classic mix-up: a BME280 strapped to 0x77, board.yml saying 0x76.
    rep = cm.commission(C3, SimBench(C3, probe=True, i2c_present={"i2c0": [0x77]}))
    assert statuses(rep)["device:temp"] == "fail"
    assert "0x77" in detail(rep, "device:temp")


def test_probe_that_never_finishes_fails_loudly():
    rep = cm.commission(C3, SimBench(C3, probe=True, probe_hangs=True))
    st = statuses(rep)
    assert st["probe"] == "fail"
    assert st["device:temp"] == "unverified"


def test_probe_is_not_flashed_onto_the_wrong_chip():
    bench = SimBench(C3, probe=True, chip="ESP32-S3 (QFN56) (revision v0.2)")
    rep = cm.commission(C3, bench)
    assert statuses(rep)["device:temp"] == "unverified"
    assert bench.probe_runs == 0


def test_without_probe_devices_stay_one_unverified_line_pointing_at_probe():
    rep = cm.commission(C3, SimBench(C3))
    assert statuses(rep)["pins_devices"] == "unverified"
    assert "--probe" in detail(rep, "pins_devices")


# --- CLI ---------------------------------------------------------------------


def test_cli_sim_commission_probe():
    r = subprocess.run(
        MCUFLOW + ["--sim", "--json", "commission", str(C3_PATH), "--probe"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    st = {c["check"]: c["status"] for c in json.loads(r.stdout)["report"]["checks"]}
    assert st["device:temp"] == "pass"


# --- the simulator speaks the probe image's format -----------------------------


def _c_formats_by_kind(src):
    """JSON key sets of every MCUFLOW-PROBE printf format in the generated C."""
    out = {}
    # Adjacent C string literals are concatenated first, as the compiler does.
    joined = re.sub(r'"\s*\n\s*"', "", src)
    for fmt in re.findall(r"MCUFLOW-PROBE (\{.*?\})\\n", joined):
        text = fmt.replace('\\"', '"')
        text = text.replace("[%s]", "[]").replace("%u", "0").replace("%d", "0")
        obj = json.loads(text)
        out.setdefault(obj["kind"], set()).update(obj)
    return out


def test_sim_probe_output_has_the_c_images_keys_for_every_kind():
    c = _c_formats_by_kind(probe_fw.gen_main_c(C3))
    assert set(c) == {"start", "i2c_bus", "i2c_device", "i2c_scan", "done"}
    sim = {}
    for f in probe_fw.parse(SimBench(C3, probe=True).run_probe(C3)):
        sim.setdefault(f["kind"], set()).update(f)
    assert sim == c


# --- the real prober: build once per fingerprint, then flash and capture ---------

cli = importlib.util.module_from_spec(
    importlib.util.spec_from_file_location("mcuflow_cli_probe_test", MCUFLOW[1])
)
cli.__spec__.loader.exec_module(cli)


class _FakeBench:
    def __init__(self):
        self.captures = []

    def reset_capture(self, seconds=None, until=None):
        self.captures.append((seconds, until))
        return ['MCUFLOW-PROBE {"kind":"done"}']


def _probe_dir(board):
    name = probe_fw.safe_name(board["meta"]["project"]) + "-" + probe_fw.fingerprint(board)
    return ROOT / "build-out" / "_probe" / name


def test_prober_reuses_an_image_already_built_for_this_fingerprint(monkeypatch):
    board = json.loads(json.dumps(C3))
    board["meta"]["project"] = "probe-cache-test"
    out = _probe_dir(board)
    (out / "build").mkdir(parents=True, exist_ok=True)
    (out / "build" / "flasher_args.json").write_text(
        json.dumps({"flash_files": {"0x0": "bootloader/bootloader.bin"}}), encoding="utf-8"
    )
    ran = []
    monkeypatch.setattr(cli, "_run", lambda cmd, **k: ran.append(cmd) or (0, "", ""))
    bench = _FakeBench()
    try:
        lines = cli._probe_runner("MCUFLOW-TEST-NO-SUCH-PORT")(board, bench)
    finally:
        import shutil

        shutil.rmtree(out, ignore_errors=True)
    assert len(ran) == 1 and "write_flash" in ran[0]  # flashed, not rebuilt
    assert "MCUFLOW-TEST-NO-SUCH-PORT" in ran[0]
    assert bench.captures == [(15, probe_fw.DONE_LINE)]
    assert lines == ['MCUFLOW-PROBE {"kind":"done"}']


def test_prober_without_a_toolchain_says_how_to_get_one(monkeypatch):
    board = json.loads(json.dumps(C3))
    board["meta"]["project"] = "probe-notool-test"
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    monkeypatch.setattr(cli, "_cage_available", lambda image: False)
    ran = []
    monkeypatch.setattr(cli, "_run", lambda cmd, **k: ran.append(cmd) or (0, "", ""))
    try:
        raised = None
        try:
            cli._probe_runner("MCUFLOW-TEST-NO-SUCH-PORT")(board, _FakeBench())
        except RuntimeError as e:
            raised = str(e)
    finally:
        import shutil

        shutil.rmtree(_probe_dir(board), ignore_errors=True)
    assert raised and "doctor --fix" in raised
    assert ran == []  # nothing built, nothing flashed
