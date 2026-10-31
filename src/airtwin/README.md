# `airtwin` package

The Python package that implements the twin: data loading, streaming, the twin itself, experiments and the API.

| File | What it does |
|---|---|
| `__init__.py` | Package marker; holds `__version__`, kept equal to `pyproject.toml` and `CITATION.cff` |
| `config.py` | Loads `configs/default.yaml` into frozen, typed dataclasses and reports missing or mistyped keys |
| `cli.py` | The `airtwin` command: `download` (fetch and verify datasets), `prepare` (clean them into `data/processed/`), `replay` (stream a dataset and report throughput) and `check` (config and checksum health check); `--backend` overrides the stream backend |
| `data/` | Dataset download with checksum verification and the two dataset loaders ([README](data/README.md)) |
| `stream/` | The stream contract, the in-memory backend and the Kafka + Spark backend ([README](stream/README.md)) |

## How it connects

- Configuration comes from `configs/default.yaml`; no tunable value is hard-coded here.
- Each sub-package gets its own README when it is added: `twin/` (state, expected value, drift, healing, feedback, what-if, engine), `experiments/` (baselines, metrics, statistics, report) and `api/` (FastAPI app).
- `twin/engine.py` is the only module that wires twin parts together, and `api/` talks only to the engine.
- Tests for every module live in `tests/`.
