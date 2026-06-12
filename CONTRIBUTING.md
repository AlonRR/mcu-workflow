# Contributing

Thanks for your interest! `board.yml` is the contract everything derives from,
and the `mcuflow` CLI is the deterministic conductor — see the
[README](README.md) and [docs/architecture.md](docs/architecture.md).

## Setup

You don't need a pre-existing Python — uv provides it:

```sh
# install uv:  curl -LsSf https://astral.sh/uv/install.sh | sh   (or install.ps1 on Windows)
uv venv
uv pip install -e .          # deps from pyproject + the `mcuflow` command
uv run --with pre-commit pre-commit install   # auto-run lint/format/checks on commit
```

## Before opening a PR

`pre-commit` runs these on every commit; you can also run them by hand:

```sh
uv run pytest              # hardware-free regression — must pass
uv run --with ruff ruff check .           # lint — CI enforces this
uv run --with ruff ruff format .          # format — CI enforces this
```

- Keep changes small and focused; match the surrounding style.
- Update `docs/` and the relevant module `README.md` when behavior changes.
- Hardware-specific changes can't run in CI — say how you verified them on a board.
- Conventional, standard project layout is preferred over ad-hoc structure.

## Layout

Runtime code lives in `src/`, human docs in `docs/`, AI-agent material in
`agents/`, and Stage-0 hardware helpers in `hardware/`. See the layout map in the
README.
