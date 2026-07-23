"""Regression for the MCP server (src/mcpserver/mcpserver.py, architecture §12.1).

Most of this needs no MCP SDK: the tool schemas are derived from the CLI parser
and `run_tool` shells out to the real CLI, so both are exercised directly. One
guarded test does the full stdio handshake when the optional `mcp` extra is
installed; it skips cleanly otherwise, keeping the base `pytest` run green.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
C3 = str(ROOT / "examples" / "board-c3.yml")
BROKEN = str(ROOT / "examples" / "broken.yml")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


srv = _load("mcuflow_mcpserver_test", "src/mcpserver/mcpserver.py")
cli = _load("mcuflow_cli_for_mcp_test", "src/mcuflow/mcuflow.py")


# --- schema derivation (no SDK, no subprocess) -----------------------------


def test_tools_cover_the_expected_verbs():
    tools = srv.build_tools()
    assert set(tools) == {
        "validate",
        "scaffold",
        "build",
        "flash",
        "monitor",
        "test",
        "hil",
        "run",
        "doctor",
        "ports",
        "env",
    }
    # the long-running server verbs are deliberately NOT exposed
    for excluded in ("up", "workbench", "bridge", "debug", "mcp"):
        assert excluded not in tools


def test_doctor_tool_hides_mutating_flags():
    # --fix/--uninstall/--purge install or remove system state; a tool-call must
    # not trigger them. The read-only preflight (--satellite) stays.
    props = srv.build_tools()["doctor"]["schema"]["properties"]
    assert "satellite" in props
    for mutating in ("fix", "uninstall", "purge"):
        assert mutating not in props


def test_monitor_tool_requires_seconds():
    # Without --seconds the CLI monitor is a blocking interactive session, which
    # can't be a synchronous tool-call - so the tool forces the bounded mode.
    schema = srv.build_tools()["monitor"]["schema"]
    assert "seconds" in schema.get("required", [])


def test_sim_verbs_expose_sim_others_do_not():
    tools = srv.build_tools()
    for verb in ("build", "flash", "test", "hil", "run"):
        assert tools[verb]["schema"]["properties"].get("sim", {}).get("type") == "boolean"
    assert "sim" not in tools["validate"]["schema"]["properties"]


def test_ports_tool_is_the_structured_snapshot():
    tool = srv.build_tools()["ports"]
    assert tool["schema"]["properties"] == {}
    assert tool["argv"]({}) == ["--json", "ports"]


def test_schemas_do_not_invent_arguments():
    # Anti-drift: every derived property (bar the injected `sim`) must map to a
    # real argparse dest on that verb's subparser, so a tool can never reference
    # a flag the CLI doesn't have.
    choices, _ = srv._subparsers(cli.build_parser())
    for verb in srv._GENERIC_VERBS:
        dests = {a.dest for a in choices[verb]._actions if a.dest != "help"}
        excluded = srv._EXCLUDE_ARGS.get(verb, set())
        props = set(srv.build_tools()[verb]["schema"]["properties"]) - {"sim"}
        assert props <= (dests - excluded), verb


def test_build_argv_orders_globals_then_verb_then_flags():
    tools = srv.build_tools()
    # globals (--json/--sim) lead; the verb and its flags follow.
    assert tools["build"]["argv"]({"sim": True, "path": "foo"}) == [
        "--json",
        "--sim",
        "build",
        "--path",
        "foo",
    ]
    # a positional (board) with no optionals
    assert tools["validate"]["argv"]({"board": C3}) == ["--json", "validate", C3]


def test_parse_envelope_recovers_json():
    assert srv._parse_envelope('{"ok": true}') == {"ok": True}
    # a stray leading line (e.g. a re-exec notice) doesn't defeat recovery
    assert srv._parse_envelope('re-exec notice\n{"ok": false}')["ok"] is False
    assert srv._parse_envelope("") is None
    assert srv._parse_envelope("not json at all") is None


def test_additional_properties_locked_down():
    # additionalProperties:false lets the SDK's input validation reject unknown
    # args before we ever build an argv.
    for tool in srv.build_tools().values():
        assert tool["schema"]["additionalProperties"] is False
    assert isinstance(cli.build_parser(), argparse.ArgumentParser)  # sanity


# --- round-trip through the real CLI (no SDK; proves single execution path) --


def test_run_tool_validate_matches_the_cli():
    envelope, text, is_error = srv.run_tool(srv.build_tools(), "validate", {"board": C3})
    assert envelope is not None and envelope["ok"] is True
    assert envelope["exit_code"] == 0 and is_error is False
    assert text  # the display text carries the pretty-printed envelope


def test_run_tool_build_sim():
    envelope, _text, is_error = srv.run_tool(srv.build_tools(), "build", {"sim": True})
    assert envelope["ok"] is True and envelope.get("sim") is True and is_error is False


def test_run_tool_surfaces_failure():
    envelope, _text, is_error = srv.run_tool(srv.build_tools(), "validate", {"board": BROKEN})
    assert envelope is not None and envelope["ok"] is False
    assert is_error is True  # non-zero exit maps to an MCP error


def test_run_tool_unknown_tool():
    envelope, text, is_error = srv.run_tool(srv.build_tools(), "nope", {})
    assert envelope is None and is_error is True and "unknown tool" in text


# --- full stdio transport (needs the optional `mcp` extra) ------------------


def test_stdio_end_to_end():
    pytest.importorskip("mcp")
    import asyncio
    import json
    import os
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def scenario():
        env = dict(os.environ)
        env["MCUFLOW_NO_REEXEC"] = "1"
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "mcuflow.mcuflow", "mcp"], env=env
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=45)
                names = {t.name for t in (await session.list_tools()).tools}
                assert {"validate", "build", "monitor", "ports"} <= names
                r = await asyncio.wait_for(session.call_tool("validate", {"board": C3}), timeout=60)
                env_ = json.loads(r.content[0].text)
                assert env_["ok"] is True and r.isError is False

    asyncio.run(asyncio.wait_for(scenario(), timeout=120))
