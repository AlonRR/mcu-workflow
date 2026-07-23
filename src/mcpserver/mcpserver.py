#!/usr/bin/env python3
"""
mcpserver.py - expose the mcuflow CLI verbs as MCP tools (architecture §12.1).

Transport, not reimplementation. Every tool shells out to `mcuflow <verb>
--json` - the same binary CI, scripts, and a human at a prompt run - and relays
the JSON envelope back. There is no second path to idf.py/esptool, so the tools
cannot drift from the CLI.

The tool input-schemas are DERIVED from the CLI's own argparse parser (the same
single-source trick `_global_flag_strings` uses), so a verb that gains a flag
updates its tool automatically.

stdio transport only (v1): the client launches this as a child process and talks
over stdin/stdout, so there is no listening port to secure and the cage boundary
(§6-7) still holds. Requires the optional `mcp` extra:

    uv pip install -e ".[mcp]"

See docs/mcp-server.md for the design and the deliberately-excluded verbs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

# Verbs exposed as tools, derived generically from their CLI subparsers.
# Everything not here is intentionally out: up/workbench/bridge/debug are
# long-running servers (nothing to synchronously return); see docs/mcp-server.md.
_GENERIC_VERBS = [
    "validate",
    "scaffold",
    "build",
    "flash",
    "monitor",
    "test",
    "hil",
    "run",
    "doctor",
    "env",
]
# Verbs for which the global --sim flag is meaningful and worth exposing.
_SIM_VERBS = {"build", "flash", "test", "hil", "run"}
# Args dropped from a verb's tool: doctor's --fix/--uninstall/--purge install or
# remove system state (Docker, usbipd, the ~15GB cage image, the .venv) - not
# something a tool-call should trigger silently. The read-only preflight stays.
_EXCLUDE_ARGS = {"doctor": {"fix", "uninstall", "purge"}}
# Tool args forced required so a verb can't be called in a mode that makes no
# sense over MCP: monitor without --seconds is the blocking interactive session.
_FORCE_REQUIRED = {"monitor": {"seconds"}}

_TYPE_MAP = {int: "integer", float: "number"}


def _require_sdk():
    """Fail clearly if the optional `mcp` extra isn't installed."""
    try:
        import mcp  # noqa: F401
    except Exception:
        sys.stderr.write(
            "mcuflow mcp: the MCP SDK is not installed.\n"
            '  Install the optional extra:  uv pip install -e ".[mcp]"\n'
        )
        raise SystemExit(127)


# --- CLI-contract introspection -------------------------------------------


def _arg_schema(action):
    """JSON-schema fragment for one argparse action (positional or option)."""
    prop = {}
    if action.help:
        prop["description"] = action.help
    if isinstance(action, argparse._StoreTrueAction):
        prop["type"] = "boolean"
    else:
        prop["type"] = _TYPE_MAP.get(action.type, "string")
    if action.choices:
        prop["enum"] = list(action.choices)
    return prop


def _verb_spec(verb, subparser):
    """Build (input-schema, argv-builder metadata) for one verb from its
    subparser, so the tool signature stays locked to the CLI."""
    positionals, optionals, props, required = [], [], {}, []
    exclude = _EXCLUDE_ARGS.get(verb, set())
    for a in subparser._actions:
        if a.dest in ("help",) or a.dest in exclude:
            continue
        if not a.option_strings:  # positional
            if a.nargs == argparse.REMAINDER:
                continue
            positionals.append(a.dest)
            props[a.dest] = _arg_schema(a)
            required.append(a.dest)
        else:  # option
            option = next((o for o in a.option_strings if o.startswith("--")), a.option_strings[0])
            optionals.append(
                {
                    "dest": a.dest,
                    "option": option,
                    "is_flag": isinstance(a, argparse._StoreTrueAction),
                }
            )
            props[a.dest] = _arg_schema(a)
            if a.required:
                required.append(a.dest)
    if verb in _SIM_VERBS:
        props["sim"] = {
            "type": "boolean",
            "description": "simulate (no toolchain or hardware needed)",
        }
    for name in _FORCE_REQUIRED.get(verb, set()):
        if name in props and name not in required:
            required.append(name)
    schema = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = required
    return {"positionals": positionals, "optionals": optionals, "schema": schema}


def _build_argv(verb, spec, arguments):
    """Turn a tool-call's arguments back into a `mcuflow` argv. Globals (--json,
    --sim) lead; the verb and its own flags follow."""
    head = ["--json"]
    if verb in _SIM_VERBS and arguments.get("sim"):
        head.append("--sim")
    tail = []
    for name in spec["positionals"]:
        if arguments.get(name) is not None:
            tail.append(str(arguments[name]))
    for o in spec["optionals"]:
        val = arguments.get(o["dest"])
        if val is None:
            continue
        if o["is_flag"]:
            if val:
                tail.append(o["option"])
        else:
            tail += [o["option"], str(val)]
    return head + [verb] + tail


def _subparsers(parser):
    """(verb -> subparser, verb -> help) from the top-level parser."""
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            return a.choices, {ca.dest: ca.help for ca in a._choices_actions}
    return {}, {}


def build_tools():
    """name -> {description, schema, argv(arguments)} for every exposed tool.

    Imports the CLI's parser purely to read it - execution still shells out, so
    this introspection doesn't add a second execution path."""
    from mcuflow.mcuflow import build_parser

    choices, helps = _subparsers(build_parser())
    tools = {}
    for verb in _GENERIC_VERBS:
        spec = _verb_spec(verb, choices[verb])
        tools[verb] = {
            "description": helps.get(verb) or verb,
            "schema": spec["schema"],
            "argv": (lambda a, v=verb, s=spec: _build_argv(v, s, a)),
        }
    # ports: the structured snapshot only. The verb's GUI/--watch modes would
    # open a window or block, so they're not exposed - the tool always runs the
    # side-effect-free `ports --json`.
    tools["ports"] = {
        "description": "list connected boards / COM-port mapping (structured snapshot)",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "argv": (lambda a: ["--json", "ports"]),
    }
    return tools


# --- execution -------------------------------------------------------------


def _run_cli(argv):
    """Run the mcuflow CLI as a subprocess; return (returncode, stdout, stderr).
    Using the current interpreter keeps us on the same (venv) Python the server
    runs under, and capturing the child's stdout keeps it off our own stdout -
    which, under stdio transport, is the JSON-RPC channel."""
    cmd = [sys.executable, "-m", "mcuflow.mcuflow"] + list(argv)
    # stdin=DEVNULL: the CLI never reads stdin, and under stdio transport our own
    # stdin is the JSON-RPC pipe - letting the child inherit it risks a deadlock.
    proc = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return proc.returncode, proc.stdout, proc.stderr


def _parse_envelope(out):
    """The CLI prints one JSON object with --json; recover it even if a stray
    line precedes it (e.g. a re-exec notice)."""
    out = (out or "").strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        pass
    for line in reversed(out.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except Exception:
            continue
    return None


def run_tool(tools, name, arguments):
    """Execute one exposed tool by shelling out to the CLI, and return
    (envelope_or_None, display_text, is_error).

    SDK-free on purpose - the MCP handler wraps this in content types, but the
    real work (argv build -> subprocess -> envelope) is a plain function so it's
    unit-testable without a running server. rc is the single source of truth for
    success (it equals the envelope's exit_code, and covers verbs like `ports`
    whose snapshot carries no "ok" field)."""
    tool = tools.get(name)
    if tool is None:
        return None, "unknown tool: " + str(name), True
    rc, out, err = _run_cli(tool["argv"](arguments or {}))
    envelope = _parse_envelope(out)
    if envelope is None:
        text = (out + err).strip() or ("mcuflow exited " + str(rc) + " with no output")
        return None, text, True
    return envelope, json.dumps(envelope, indent=2), rc != 0


# --- server ----------------------------------------------------------------


def _serve_stdio():
    _require_sdk()
    import anyio
    import mcp.types as types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    tools = build_tools()
    server = Server("mcuflow")

    @server.list_tools()
    async def _list_tools():
        return [
            types.Tool(name=name, description=t["description"], inputSchema=t["schema"])
            for name, t in tools.items()
        ]

    @server.call_tool()
    async def _call_tool(name, arguments):
        # Shell out on a worker thread so the event loop stays responsive.
        envelope, text, is_error = await anyio.to_thread.run_sync(
            run_tool, tools, name, arguments or {}
        )
        content = [types.TextContent(type="text", text=text)]
        if envelope is not None:
            return types.CallToolResult(
                content=content, structuredContent=envelope, isError=is_error
            )
        return types.CallToolResult(content=content, isError=is_error)

    async def _run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(_run)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="mcuflow mcp",
        description="Run the mcuflow MCP server (exposes the CLI verbs as MCP tools).",
    )
    ap.add_argument(
        "--transport", choices=["stdio"], default="stdio", help="MCP transport (v1: stdio only)"
    )
    ap.add_argument("--verbose", action="store_true", help="log server diagnostics to stderr")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if args.verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
    _serve_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
