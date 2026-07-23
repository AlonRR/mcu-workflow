# Exposing `mcuflow` as an MCP server

*v1.0 · 2026-07-23 · implements architecture §12.1*

**Status: built.** Shipped as `mcuflow mcp` (`src/mcpserver/mcpserver.py`), with
the module quick-start in [`src/mcpserver/README.md`](../src/mcpserver/README.md)
and tests in `tests/test_mcpserver.py`. This document is the design record: what
was decided and why, including the alternatives considered but not taken. Every
recommendation below was adopted as built unless noted.

## 1. Purpose

Give an MCP client — Claude Code, an editor, or the in-cage agent — first-class
tool-calls for the microcontroller loop: `validate`, `scaffold`, `build`,
`flash`, `test`, `hil`, `run`, `doctor`, `ports`, and a bounded `monitor`. This
is the deliverable tracked in [architecture.md §12.1](architecture.md); read
that section first — it fixes the intent and the constraints, and this doc is
the concrete build plan under it.

The whole reason this is cheap: the CLI is already **the single canonical
execution path**, defined by a stable contract (JSON in/out via the global
`--json` flag, documented exit codes `0`/`1`/`2`/`127`) rather than by its
language. The server is therefore a **transport, not a reimplementation** — it
adds no second route to `idf.py`/`esptool` and so cannot drift from CI, scripts,
or a human at a prompt. This is the same argument that made Espressif's Tools
MCP server a *complement* rather than our foundation.

## 2. Inherited commitments (non-negotiable)

These come straight from the rest of the design and bound every decision below:

- **One execution path.** The shim calls the existing CLI contract. It must
  never inline `idf.py`/`esptool`.
- **Platform-agnostic.** Anything platform-specific stays behind
  `adapters.get_adapter(meta.platform)`, exactly where the CLI already routes
  it. The shim must not become a new place ESP assumptions accumulate.
- **Complements Espressif's servers.** Their Docs MCP stays the grounding source
  for hardware/API decisions; their Tools MCP stays optional. This server covers
  the toolchain half (build/flash/monitor/board-detect/HIL) that the MCP
  ecosystem otherwise leaves empty.
- **The cage boundary still applies (§6–7).** An MCP client must not become a
  way around egress-allowlisting, credential isolation, or the host-command
  limits. stdio (below) keeps the v1 server local by construction.
- **In-repo.** Ships as a `mcuflow mcp` subcommand — one artifact, one version —
  so the contract and its transport are versioned together. (This resolves
  §12.1's open sub-question in favour of the in-repo default.)

## 3. The core decision: how the shim invokes verbs

**The shim shells out to `mcuflow <verb> --json …` as a subprocess and relays
the parsed envelope.**

This is the most faithful reading of "transport, not reimplementation": the
server runs *literally the same binary* an agent, CI, or a human runs, so there
is zero drift surface. It also sidesteps a concrete hazard unique to stdio MCP:
**stdout is the JSON-RPC framing channel**, but the CLI's `emit()` prints its
result to stdout. An in-process call would corrupt the protocol stream unless
stdout were carefully redirected; a subprocess captures the child's stdout
cleanly and leaves the server's own stdout untouched. Subprocess cost (a few
hundred ms plus a venv re-exec) is negligible against build/flash/test
wall-clock.

*Considered and deferred:* importing and calling the `verb_*` functions
in-process with `contextlib.redirect_stdout`. Faster, but it re-introduces a
drift surface and the stdout-hijack risk for marginal benefit on operations that
already take seconds. Revisit only if latency ever becomes a real complaint.

## 4. Transport — stdio for v1

The transport is the channel the JSON-RPC messages ride on.

- **stdio (chosen).** The client launches the server as a child process and
  talks over stdin/stdout. Local-only, no listening port, no auth to design —
  the OS process boundary is the security. This matches `idf.py mcp-server` and
  the way editors run local MCP servers. The agent that drives build/flash runs
  *beside* the workspace (in the cage, project mounted), so it reaches the
  toolchain by launching a local process, not over the network.
- **HTTP/SSE (deferred).** A long-running network service reached by URL —
  needed only when client and server are on different machines (remote or
  networked-workbench placement, the §9 world). It adds a bind address, an open
  port, and auth that §7 would have to secure — real surface area for no v1
  benefit. Transport is a `--transport` flag, so adding HTTP later is additive,
  never a rewrite.

## 5. Implementation — official MCP SDK as an optional extra

MCP is more than "print JSON": there is an `initialize` handshake, capability
negotiation, `tools/list`/`tools/call`, notifications, content-type envelopes,
error formats, and protocol-version handling, all of which must stay compatible
across many clients as the spec evolves.

- **Official `mcp` Python SDK (`FastMCP`), chosen.** It owns that protocol
  plumbing; we register tools and their schemas. Reimplementing the wire
  protocol to save a dependency would contradict the project's first principle,
  *wrap, don't reinvent*, and the whole point of MCP is broad client interop.
- **Optional extra, so the base CLI stays lean.** The SDK lands under a new
  `[project.optional-dependencies] mcp = […]`, mirroring the existing `dev`
  extra. The base install keeps its four runtime deps
  (`pyyaml`/`jsonschema`/`pyserial`/`esptool`); only someone running the server
  pulls the SDK, via `uv pip install -e ".[mcp]"`. If the extra is absent,
  `mcuflow mcp` exits with a clear "install `mcuflow[mcp]`" message, in the same
  spirit as the CLI's existing missing-tool handling.

*Considered and rejected:* a hand-rolled stdlib JSON-RPC loop (matching
`workbench.py`'s stdlib-only ethos). Zero new deps, but it reimplements the
protocol, owns the spec-compat burden, and risks subtle client-interop bugs —
the wrong trade for a protocol whose value *is* interoperability.

## 6. Placement — fits the existing sibling-module pattern

The MCP server is a standalone long-running service, like `workbench`. It slots
into the established seam with no new mechanism:

- **New module** `src/mcpserver/mcpserver.py`. The directory is `mcpserver`, not
  `mcp`, so it never shadows `import mcp` (the SDK). No `__init__.py`, consistent
  with the other sibling services loaded at runtime.
- **`_SIBLINGS` entry** `"mcp": ("mcuflow_mcpserver", "mcpserver/mcpserver.py")`.
- **`verb_mcp`** delegating via `_sibling("mcp").main(args.rest)`.
- **`passthrough_keys`** gains `"mcp"` in `main()` so the server's own flags
  (`--transport`, `--verbose`) pass through the pre-argparse dispatch untouched,
  exactly like `workbench` and `up`.
- **Subparser** `mcuflow mcp` with `nargs=REMAINDER`.

One parser import, one table entry, one passthrough key — the pattern carries
the rest.

## 7. Tool surface

§12.1's list is `validate scaffold build flash monitor test hil run ports
doctor`. Split by whether a verb is naturally request/response:

| Verb | MCP tool | Notes |
|---|---|---|
| `validate` | direct | `board` path in, envelope out |
| `scaffold` | direct | `board` + optional `out` |
| `build` | direct | `--sim` exposed as a parameter |
| `flash` | direct | `--port`, `--sim` |
| `test` | direct | pytest file (or board.yml with `--sim`) |
| `hil` | direct | `--satellite`, `--workbench`, `--sim` |
| `run` | direct | composite; returns the per-stage structured result |
| `doctor` | direct | preflight; `--satellite` optional |
| `ports` | direct | backed by `ports --json` (the structured snapshot) |
| `env doctor` | direct | build-readiness check |
| `monitor` | **adapted** | see below |

**The `monitor` adaptation.** The CLI `monitor` is an interactive serial session
that blocks indefinitely — that does not map to a synchronous tool-call. Expose
it as a **bounded read**: capture serial for a `duration_s` (or until a
`boot_string` / N lines) and return the transcript. This reuses the timed
serial-capture capability the HIL path already proves out, rather than inventing
a streaming tool.

**Deliberately excluded from v1:** `up`, `workbench`, `bridge`, `debug`. These
*are themselves* long-running servers — a tool-call that starts one has nothing
to synchronously return — and none appear in §12.1's list. The exclusion is a
decision, not a gap; it is recorded here so it reads that way.

### Tool schemas — derived from the parser, not hand-written

The repo's idiom is to derive from the single source so it cannot drift (e.g.
`_global_flag_strings` reads the argparse parser). Apply it here: **generate each
tool's input JSON-schema by introspecting the argparse subparser** — argument
names, `type`, `default`, `help`, `choices`, and required-ness. A hand-kept
schema table would be a fresh drift surface; deriving keeps every tool signature
locked to the CLI it fronts. This mapper is the one piece of genuine logic in
the shim and the part worth testing hardest.

### Errors — relay the envelope, map the exit code

Each handler builds the `mcuflow <verb> --json <args>` argv, runs it, and parses
the envelope. A non-zero exit code surfaces as an MCP tool error **with the
envelope still relayed**, so the agent sees `detail` / `missing_tool` and can
act — mirroring how the CLI already reports failures to a human.

## 8. Build steps

1. **Packaging** — add `[project.optional-dependencies] mcp = ["mcp>=<pin>"]` to
   `pyproject.toml`; document `uv pip install -e ".[mcp]"` in the module README.
2. **Server module** `src/mcpserver/mcpserver.py`:
   - `main(argv)` parses `--transport stdio` (default) and `--verbose`; builds a
     low-level `mcp.server.lowlevel.Server` named `"mcuflow"`. (The low-level
     `Server` was chosen over `FastMCP` because it lets each tool carry an
     explicit `inputSchema` — which is what makes the *parser-derived* schemas
     possible; `FastMCP` derives schemas from Python function signatures, which
     would reintroduce the drift this design avoids.)
   - the argparse→JSON-schema mapper (`_verb_spec`); register one tool per
     exposed verb via `list_tools`.
   - per-tool handler (`run_tool`, SDK-free so it's unit-testable): assemble
     argv, run via subprocess (`stdin=DEVNULL` — our stdin is the JSON-RPC pipe),
     parse and relay the envelope, map the exit code (§7).
   - `monitor` uses the CLI's new bounded `monitor --seconds` capture.
   - a clean "install `.[mcp]`" exit (127) when the SDK import fails.
3. **CLI wiring** in `src/mcuflow/mcuflow.py`: the `_SIBLINGS` entry, `verb_mcp`,
   the subparser, and the `passthrough_keys` addition.

## 9. Testing (`tests/test_mcpserver.py`)

Mirror `tests/test_workbench.py` conventions, and guard the SDK-dependent cases
so the base `pytest` run (no `[mcp]` extra) still passes — `skip` when `mcp`
isn't importable:

- **Schema generation** — every exposed verb yields a valid tool schema; a verb
  added to the parser without a corresponding tool is caught.
- **Round-trip** — invoke each tool against `examples/board-c3.yml` with
  `--sim`; assert the relayed envelope matches running the CLI directly (proves
  the single-execution-path claim).
- **Exit-code mapping** — a failing verb surfaces as an MCP error with the
  envelope intact.
- **No-SDK path** — `mcuflow mcp` without the extra prints the install hint and
  exits non-zero.

## 10. Docs updated on landing (done)

- **This file** — header flipped from *plan* to the design record it now is.
- **[architecture.md](architecture.md)** — §12.1 marked *built*, the in-repo
  sub-question resolved, and the server added to the §10 deliverables note.
- **[docs/README.md](README.md)** — per-module row for `src/mcpserver/`.
- **[src/mcpserver/README.md](../src/mcpserver/README.md)** — the module
  reference: client-registration snippet, the tool list, the `monitor`
  adaptation, and the cage-boundary note.
- **[README.md](../README.md)** / **[CHANGELOG.md](../CHANGELOG.md)** — verb list,
  repo-layout tree, and an Unreleased entry.

## 11. Out of scope for v1

HTTP/SSE transport, streaming `monitor`, exposing the server-verbs
(`up`/`workbench`/`bridge`/`debug`) as tools, and any transport-level auth —
stdio is local-only, and the cage wall (§7) remains the boundary. Each is an
additive change if a real need appears.
