# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- One-line bootstrap installers (`install.sh`, `install.ps1`): install uv, a
  Python, the repo, and all prerequisites, and put `mcuflow` on PATH — nothing
  needs to pre-exist.
- `pyproject.toml`: standard installable layout, a `mcuflow` console script, and
  dependencies as the single source of truth.
- `mcuflow doctor --fix` self-install and `doctor --uninstall` / `--purge`
  teardown.
- Cage build + host `esptool` flash, so no native ESP-IDF install is needed.
- On-silicon HIL: `run`/`hil` read the real DUT serial to confirm boot + WiFi join.
- `ruff` lint gate and CI (smoke + lint).

### Changed
- Reorganized the repository into `src/`, `docs/`, `agents/`, `hardware/`,
  `deploy/`, with examples at the top level.

## [0.2.0]

- First end-to-end run on real two-ESP32-C3 hardware: validate → scaffold →
  build → flash → workbench-mediated HIL, all green.
- ESP-IDF v6.0 fixes (managed `espressif/cjson`, split `esp_driver_*`
  components) and a boot-noise-tolerant satellite host driver.
