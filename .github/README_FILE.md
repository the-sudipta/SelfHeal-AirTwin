# `.github`

GitHub automation and contributor forms for this repository.

| File | What it does |
|---|---|
| `workflows/ci.yml` | On every push and pull request to `main`: job `checks`: installs the hashed lock on Python 3.11, then runs ruff lint, ruff format check, mypy and pytest with coverage; job `image`: builds the Docker image (datasets verified during the build), runs the health check, a memory-backend replay, the reproduce smoke test and the live twin, starts Kafka, runs the real Kafka + Spark test inside the image, a Kafka-backend replay and the live twin on Kafka + Spark |
| `workflows/pages.yml` | On pushes that change the site, the web twin, the visuals or the reference tables: assembles the landing page, the web twin in replay mode, `assets/` and the reference tables, and deploys them to GitHub Pages |
| `workflows/release.yml` | On every `v*` tag: builds the image from the tag, pushes it to GitHub Container Registry, attests its build provenance, writes an SPDX SBOM, reruns every experiment inside the released image and stops unless `verify` passes, then attaches `results.tar.gz`, `SHA256SUMS`, `sbom.spdx.json` and `IMAGE_DIGEST.txt` to the GitHub Release |
| `live-check.sh` | Waits until a running live twin streams live ticks, then checks the state API, the web twin page and the inject command |
| `dependabot.yml` | Weekly grouped update proposals for GitHub Actions and Python dependencies |
| `ISSUE_TEMPLATE/bug_report.yml` | Form for bugs, asking for exact commands and version |
| `ISSUE_TEMPLATE/reproducibility.yml` | Form for results that do not match, asking for `airtwin verify` output and image digest |
| `ISSUE_TEMPLATE/config.yml` | Disables blank issues and routes security reports to private advisories |
| `PULL_REQUEST_TEMPLATE.md` | What / Why / How sections and the pre-merge checklist |

## How it connects

- CI uses `requirements.lock` and the tool settings in `pyproject.toml`, the same as the local checks in `CONTRIBUTING.md`.
- Every action is pinned to a full commit SHA (see `INTEGRITY.md`); the CI check is required by the `main` branch ruleset.
- Pages and Release need two owner settings: Pages served from GitHub Actions, and the container package made public (see `INTEGRITY.md`).
