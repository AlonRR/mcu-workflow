# ci-templates — GitHub Actions (deliverable #11)

CI pipeline templates. They live here (not in `.github/`) so they don't run on this tooling repo — copy them into a generated project.

- **`github/build.yml`** → `.github/workflows/build.yml`. The fast gate: validates `board.yml` and builds firmware in the pinned ESP-IDF container on a GitHub-hosted runner. No hardware needed; runs on every push/PR.
- **`github/hil.yml`** → `.github/workflows/hil.yml`. The authoritative gate: builds, flashes, and runs pytest-embedded on a **self-hosted runner with the board attached**.

## Why self-hosted for HIL

Cloud runners have no USB and no board. The HIL job therefore targets a self-hosted runner, selected by labels:

```yaml
runs-on: [self-hosted, esp32s3, generic]
```

Those labels are the chip + instrument routing from `ARCHITECTURE.md` Section 8 — a job needing BLE would add `ble`, and only a runner tagged for it picks the job up. Set a runner's labels when you register it (`./config.sh --labels self-hosted,esp32s3,generic,ble`), ideally from the board-detection step so plugging in hardware updates the tags automatically.

## Relationship to mcuflow

CI is thin on purpose: it checks out, then calls the same `mcuflow` verbs (or `idf.py`/`pytest`) you run locally, so CI and local behavior never diverge (see "Who orchestrates" in `ARCHITECTURE.md`). `build.yml` prefers `tools/mcuflow/mcuflow.py` when vendored and falls back to `idf.py`.

## GitLab

The same two stages map directly onto `.gitlab-ci.yml` with a `tags:`-based runner selection instead of `runs-on:`; GitHub is the chosen default (Section 13).
