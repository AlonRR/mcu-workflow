# mcpserver — `mcuflow mcp`

Expose the `mcuflow` CLI verbs as **MCP tools** so an MCP client (Claude Code, an
editor, or the in-cage agent) can drive build/flash/test/HIL as tool-calls.
Implements [architecture.md §12.1](../../docs/architecture.md); the design and
the deliberately-excluded verbs are in
[docs/mcp-server.md](../../docs/mcp-server.md).

It is a **transport, not a reimplementation**: every tool shells out to
`mcuflow <verb> --json` — the same binary CI, scripts, and a human at a prompt
run — and relays the JSON envelope. The tool input-schemas are *derived from the
CLI's own argparse parser*, so a verb that gains a flag updates its tool
automatically and the two cannot drift.

## Install & run

The MCP SDK is an **optional** extra, so the base CLI stays dependency-light:

```sh
uv pip install -e ".[mcp]"    # adds the `mcp` SDK
mcuflow mcp                    # start the server on stdio (v1: stdio only)
```

Without the extra, `mcuflow mcp` prints an install hint and exits 127.

## Register it with a client

Point any MCP client at the command. For Claude Code (`mcpServers` config):

```json
{
  "mcpServers": {
    "mcuflow": { "command": "mcuflow", "args": ["mcp"] }
  }
}
```

## Tools

Derived from the request/response verbs: `validate`, `scaffold`, `build`,
`flash`, `monitor`, `test`, `hil`, `run`, `doctor`, `ports`, `env`. `build`,
`flash`, `test`, `hil`, and `run` take a `sim` boolean (dry-run, no
hardware/toolchain). Each tool returns the CLI's JSON envelope as both text and
`structuredContent`; a non-zero exit maps to an MCP error with the envelope still
attached.

Three adaptations to note:

- **`monitor` is a bounded capture.** The interactive session can't be a
  synchronous tool-call, so the tool requires `seconds` (and optionally `until`)
  and returns the captured serial transcript — backed by the CLI's
  `monitor --seconds` mode.
- **`ports` is the structured snapshot** (`ports --json`); the GUI/`--watch`
  modes aren't exposed.
- **`doctor` hides `--fix`/`--uninstall`/`--purge`.** Those install or remove
  system state (Docker, usbipd, the ~15 GB cage image, the `.venv`) and must not
  be triggered by a tool-call; the read-only preflight stays.

Deliberately **not** exposed: `up`, `workbench`, `bridge`, `debug` — they are
long-running servers, so a tool-call that starts one has nothing to
synchronously return.

## Boundaries

stdio transport only (v1): the client launches the server as a child process, so
there is no listening port to secure and the cage boundary
([architecture §6–7](../../docs/architecture.md)) still holds. An MCP client is
not a way around it.
