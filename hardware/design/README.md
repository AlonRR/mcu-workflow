# design — Stage 0 design assistant (deliverable #6)

Helps a beginner go from an idea to a buildable, buyable hardware design. Two parts:

- **`design.py`** — the deterministic helpers: turn the parts recorded in `board.yml` into a bill of materials with purchase links, a wiring guide, and a power budget.
- **`SKILL.md`** — the agent-facing skill that runs the conversation (describe → choose modules → record into `board.yml` → BOM/wiring/power), grounded by the Docs MCP server and web search.
- **`parts_db.yaml`** — starter current-draw figures for the power budget (extendable).

This is Phase 0: independent of the firmware loop and useful on its own.

## Use (the deterministic helpers)

```bash
# uv runs it with no pre-installed Python (pyyaml is the only dep):
uv run --no-project --with pyyaml -- python design.py links BME280   # vendor search URLs
uv run --no-project --with pyyaml -- python design.py bom    board.yml  # parts list + links
uv run --no-project --with pyyaml -- python design.py wiring board.yml  # module-pin -> board-pin
uv run --no-project --with pyyaml -- python design.py power  board.yml  # rough power budget
uv run --no-project --with pyyaml -- python design.py --json power board.yml  # machine-readable
```

## What's deterministic vs the agent's job

| Step | Who |
|------|-----|
| Describe idea → choose board + modules | the agent (SKILL.md), grounded by Docs MCP + web search |
| Parts list / wiring / power budget from chosen parts | `design.py` (deterministic, testable) |
| Vendor **search** links | `design.py` (generated) |
| Specific product links + **live prices** | the agent (web search) — never fabricated |
| Custom PCB (only when justified) | the agent + KiCad; expert-reviewed before fab |

## Honesty

Power figures are rough active-current estimates to size a supply, not measurements. Search links are generic; real product links/prices are fetched live. Mains voltage and LiPo charging are flagged as needing caution. A custom PCB or wiring is a starting point to verify, never a guarantee.
