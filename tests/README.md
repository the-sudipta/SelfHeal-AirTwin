# Tests

The pytest suite: one test file per module that contains logic.

| File | What it does |
|---|---|
| `test_package.py` | Checks that the package version is semantic and identical in `airtwin/__init__.py`, `pyproject.toml` and `CITATION.cff` |

## How it connects

- Tests import the package from `src/` (set by `pythonpath` in `pyproject.toml`), so no install step is needed.
- Run locally with `pytest -q`; coverage with `pytest --cov`. CI runs the same command on every push.
- Test files are named `test_<module>.py` after the module they cover in `src/airtwin/`.
