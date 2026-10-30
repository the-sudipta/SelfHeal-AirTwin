# Tests

The pytest suite: one test file per module that contains logic.

| File | What it does |
|---|---|
| `test_package.py` | Checks that the package version is semantic and identical in `airtwin/__init__.py`, `pyproject.toml` and `CITATION.cff` |
| `test_config.py` | Loading the real and minimal configs, path resolution, unknown datasets, missing keys, wrong types, `AIRTWIN_CONFIG` |
| `test_download.py` | Checksum parsing, verified download through `file://` URLs, reuse of good copies, replacement of tampered copies, refusal on mismatch |
| `test_uci_loader.py` | Decimal commas, the `-200` tag, blank rows, hourly regularisation, duplicate timestamps, wrong layouts |
| `test_beijing_loader.py` | Nested archive with unrelated files, `NA` handling, timestamps, sorting, duplicates, wrong layouts |
| `test_cli.py` | `airtwin download` then `prepare` on a small generated project, failure exit codes, `--version` |

## How it connects

- Tests import the package from `src/` (set by `pythonpath` in `pyproject.toml`), so no install step is needed.
- Every test builds its own tiny archives in a temporary folder, so the suite needs no network and no real data.
- Run locally with `pytest -q`; coverage with `pytest --cov`. CI runs the same command on every push.
- Test files are named `test_<module>.py` after the module they cover in `src/airtwin/`.
