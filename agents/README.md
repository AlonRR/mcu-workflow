# agents/ — material for AI coding agents

Everything in this folder is written **for an AI coding agent** (Claude Code or
similar), not for the human reading the project. It's kept separate from the
human docs (`docs/`) and the source (`src/`) so the distinction is obvious.

| File | What it is |
|---|---|
| [`onboarding.md`](onboarding.md) | The brief to paste to / point an agent at when doing the real two-board hardware bring-up. |
| [`handoff.md`](handoff.md) | The project's portable "memory": decisions, status, and resume notes mirrored into the repo so it travels as one folder (the building agent's per-machine memory does not). |
| [`skills/`](skills/) | Skill descriptors for the in-cage agent — `orchestrator`, `build-flash`, `hil-test`, `workbench-instruments`. |

Related, but kept at the repository root by convention:

- **`CLAUDE.md`** — the brief Claude Code auto-loads from the project root. It
  points the agent at `docs/` and this folder.

Module-local agent notes also live next to the code they describe (e.g.
`hardware/design/SKILL.md`). Human-facing documentation is under
[`../docs/`](../docs/).
