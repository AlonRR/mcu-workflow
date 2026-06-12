---
name: mcu-design-assistant
description: >
  Novice-friendly hardware design for a microcontroller project. Use when the
  user wants to figure out what to build or buy: "what parts do I need", "help
  me design a <device>", "which board/sensor should I use", "how do I wire
  this", "what power supply". Turns a plain-language idea into a concrete,
  buyable parts list with links, a wiring guide, and a power budget - recorded
  in board.yml. Prefers off-the-shelf modules; designs a custom PCB only when
  justified.
---

# MCU design assistant (Stage 0)

Guide a beginner from an idea to a buildable, buyable hardware design. The
guiding rule throughout: **buy a prebuilt board + breakout modules; design a
custom circuit only when there's a real reason.** Pair with the deterministic
helper `design.py` (links / bom / wiring / power) and the validator + scaffold.

## Flow

1. **Understand the goal.** Ask a few focused questions (use the question tool):
   what it should do, power source (USB / battery), connectivity (Wi-Fi / BLE /
   none), size/enclosure constraints, rough budget. Keep it short.

2. **Choose parts (module-first).** Pick one prebuilt dev board (e.g. an
   ESP32-S3 devkit) plus a breakout module per function, so nothing needs
   soldering of passives. Ground every choice in current facts: query the
   Espressif **Docs MCP** server for pin/peripheral guidance and use
   **web search** for module availability. Prefer popular, well-documented
   parts.

3. **Record into board.yml.** Write the chosen chip/board, the bus pins
   (`pins:`), each module (`devices:` with bus + address/cs/driver), the power
   profile (`power:`), and references (`hardware:`). Then run the validator
   (`../board-schema/validate.py`) and fix anything it flags.

4. **Buyable BOM.** Run `python design.py bom board.yml` for the parts list and
   instant search links. For specific products and **live prices**, use web
   search at request time - never invent a product URL or a price. Note that
   availability and price vary by region.

5. **Wiring guide.** Run `python design.py wiring board.yml`. Present the
   module-pin -> board-pin table plainly. Remind the user to check each module's
   VCC voltage (3V3 vs 5V) before powering on.

6. **Power budget.** Run `python design.py power board.yml` to size a supply or
   battery. Present it as an estimate, not a guarantee.

7. **Custom PCB - only if justified.** If modules are too bulky/fragile or the
   volume is high, propose a custom board: schematic + layout in KiCad, fab via
   JLCPCB/PCBWay. State clearly that a custom board should get an expert review
   before paying for fabrication.

## Safety and honesty (always)

- Flag mains voltage and LiPo charging as needing caution; don't treat them as
  beginner-safe.
- Never claim a generated design or wiring is guaranteed correct - it's a
  starting point to verify.
- Dimensions (for the enclosure, deliverable #7) must come from a datasheet or
  calipers, not a guess.

## Hand-offs

- `board.yml` -> the scaffold generator (deliverable #3) to start firmware.
- `enclosure:` in board.yml -> the enclosure generator (deliverable #7).
