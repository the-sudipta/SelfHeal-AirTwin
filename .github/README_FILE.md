# `.github`

GitHub automation and contributor forms for this repository.

| File | What it does |
|---|---|
| `workflows/ci.yml` | On every push and pull request to `main`: installs the hashed lock on Python 3.11, then runs ruff lint, ruff format check, mypy and pytest with coverage |
| `dependabot.yml` | Weekly grouped update proposals for GitHub Actions and Python dependencies |
| `ISSUE_TEMPLATE/bug_report.yml` | Form for bugs, asking for exact commands and version |
| `ISSUE_TEMPLATE/reproducibility.yml` | Form for results that do not match, asking for `airtwin verify` output and image digest |
| `ISSUE_TEMPLATE/config.yml` | Disables blank issues and routes security reports to private advisories |
| `PULL_REQUEST_TEMPLATE.md` | What / Why / How sections and the pre-merge checklist |

## How it connects

- CI uses `requirements.lock` and the tool settings in `pyproject.toml`, the same as the local checks in `CONTRIBUTING.md`.
- Every action is pinned to a full commit SHA (see `INTEGRITY.md`); the CI check is required by the `main` branch ruleset.
- Docker build, reproduce smoke test, release and Pages workflows are added by later milestones.
