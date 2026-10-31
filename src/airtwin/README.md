# `airtwin` package

The Python package that implements the twin: data loading, streaming, the twin itself, experiments and the live API.

| File | What it does |
|---|---|
| `__init__.py` | Package marker; holds `__version__`, kept equal to `pyproject.toml` and `CITATION.cff` |
| `config.py` | Loads `configs/default.yaml` into frozen, typed dataclasses and reports missing or mistyped keys |
| `cli.py` | The `airtwin` command: `download` (fetch and verify datasets), `prepare` (clean them into `data/processed/`), `replay` (stream a dataset and report throughput), `twin` (run the full twin and print events, the maintenance list and a what-if), `reproduce`, `verify` and `report` (the experiments), `serve` (the live twin and the web twin) and `check` (config and checksum health check); `--backend` overrides the stream backend |
| `api/` | The live twin over HTTP: background run, REST endpoints, Server-Sent Events and the web twin's files ([README](api/README.md)) |
| `data/` | Dataset download with checksum verification, the two dataset loaders and loading either dataset by name ([README](data/README.md)) |
| `stream/` | The stream contract, the in-memory backend and the Kafka + Spark backend ([README](stream/README.md)) |
| `experiments/` | Drift injection, baselines, metrics, statistics, ablation, runner, report and verification ([README](experiments/README.md)) |
| `twin/` | The digital twin: state, expected value, drift detection, self-healing, feedback, what-if and the engine ([README](twin/README.md)) |

## How it connects

- Configuration comes from `configs/default.yaml`; no tunable value is hard-coded here.
- `twin/engine.py` is the only module that wires twin parts together, and `api/` talks only to the engine.
- Tests for every module live in `tests/`.
