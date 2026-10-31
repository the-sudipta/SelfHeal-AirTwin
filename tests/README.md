# Tests

The pytest suite: one test file per module that contains logic.

| File | What it does |
|---|---|
| `test_package.py` | Checks that the package version is semantic and identical in `airtwin/__init__.py`, `pyproject.toml` and `CITATION.cff` |
| `test_config.py` | Loading the real and minimal configs, path resolution, unknown datasets, stream, Kafka, twin and drift section checks, missing keys, wrong types, `AIRTWIN_CONFIG` |
| `test_download.py` | Checksum parsing, verified download through `file://` URLs, reuse of good copies, replacement of tampered copies, refusal on mismatch |
| `test_uci_loader.py` | Decimal commas, the `-200` tag, blank rows, hourly regularisation, duplicate timestamps, wrong layouts |
| `test_beijing_loader.py` | Nested archive with unrelated files, `NA` handling, timestamps, sorting, duplicates, wrong layouts |
| `test_interface.py` | Frozen readings, observed values, unique sorted sites per tick, strict time order |
| `test_memory_stream.py` | Grouping rows into ticks, NaN kept, limit, pause, close, single-site tables, invalid input, protocol conformance |
| `test_kafka_stream.py` | JSON encoding with NaN, tick reassembly from split and reordered batches, equality with the memory backend through a fake transport, limit, pause, close, publish failure, idle timeout, the backend factory; one real Kafka + Spark round trip that runs only when `AIRTWIN_KAFKA_TEST_BOOTSTRAP` is set (in CI, inside the image) |
| `test_state.py` | Sensor keys and their text form, corrections, residual and corrected value, frozen sorted snapshots and their queries |
| `test_expected_model.py` | Flattening ticks, feature specs and the `use_*` switches, learning a known relationship, missing inputs, deterministic training, untrained sensors, calibration then prediction |
| `test_drift_detector.py` | Rolling median with gaps, baseline level, robust spread and observed smoothed spreads, warm-up with too few raw or smoothed points, no alarm on stationary noise, step drift confirmed with direction for each method, slow negative drift, watch before confirmation, reset, missing hours pausing the statistics, the per-sensor bank |
| `test_self_healer.py` | Gain and offset recovery, outliers and gaps, offset-only mode, gain bounds, too few pairs, proposals with evidence, accept and deactivate, heal, refit interval, fit windows, clear, relative effect |
| `test_feedback.py` | Ranking by error and duration, listing threshold, confirmed drift without correction, ties, readable reasons |
| `test_what_if.py` | Linear trend extrapolation, history window, single correction, healthy sensor |
| `test_engine.py` | A four-site stream where one site drifts by +40 %: calibration, warm-up, detection only on the drifting site, correction near the true gain, maintenance list, what-if, mark-recalibrated; unconvincing or wrong-direction corrections dismissed; a temporary shift corrected and then retired; and the same stream without trust substitution, where healthy neighbours get blamed |
| `test_cli.py` | `airtwin download`, `prepare` and `replay`, `twin` (with and without event output) and `check` on a small generated project, the `--backend` override, failure exit codes, `--version` |

## How it connects

- Tests import the package from `src/` (set by `pythonpath` in `pyproject.toml`), so no install step is needed.
- Every test builds its own tiny archives in a temporary folder, so the suite needs no network and no real data; the one Kafka test is skipped unless a broker is available.
- Run locally with `pytest -q`; coverage with `pytest --cov`. CI runs the same command on every push.
- Test files are named `test_<module>.py` after the module they cover in `src/airtwin/`.
