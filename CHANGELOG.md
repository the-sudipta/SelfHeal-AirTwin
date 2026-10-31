# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

## [0.6.0] - 2026-10-31

Drift detection.

### Added

- `airtwin.twin.drift_detector`: per-sensor detector that learns the normal residual level and robust spread in a 30-day baseline, smooths the residual with a 24-hour rolling median, and runs an EWMA and a two-sided CUSUM with limits measured on the baseline (real air-quality residuals are autocorrelated, so textbook limits for independent noise do not apply). One drift score (1.0 = alarm line) drives healthy, watch and drifting; drift is confirmed after 24 consecutive alarm hours and stays confirmed until reset by the self-healer.
- `twin.drift` configuration section with range checks.

### Changed

- The calibration window of the expected-value models is now set per dataset: one year for Beijing, so the models see every season; 30 days for UCI.

### Design evidence

- Selected on years 1–2 of Beijing only (years 3–4 untouched): with the defaults, 5.9 confirmed alarms per 1,000 hours per sensor without injected drift, and all 216 injected step drifts of 10 %, 20 % and 30 % confirmed with median delays of 98, 58 and 60 hours. A 30-day calibration produced 12–34 alarms per 1,000 hours; neighbour consensus and an adapting baseline did not help.

[0.6.0]: https://github.com/the-sudipta/SelfHeal-AirTwin/releases/tag/v0.6.0

## [0.5.0] - 2026-10-31

Twin state and the expected-value model (the virtual entity).

### Added

- `airtwin.twin.state`: `SensorKey`, `SensorStatus`, `Correction` (offset and gain), `SensorState` with derived residual and corrected value, and the frozen hourly `TwinSnapshot`, the typed interface between all twin parts.
- `airtwin.twin.expected_model`: one deterministic, single-threaded LightGBM regressor per sensor predicts the value the sensor should read from the same variable at neighbouring sites, local weather, the reference analyzer and the hour of day; a sensor's own reading is never an input. `ExpectedValueBank` learns from a 720-hour calibration window and then predicts every hour.
- `twin` section in `configs/default.yaml`: calibration window, LightGBM parameters, and per dataset the twinned variables and the `use_neighbours`, `use_weather`, `use_reference` and `use_time` switches used later for ablation. 72 Beijing sensors (12 sites × 6 pollutants) and 5 UCI sensors are twinned.
- LightGBM 4.7.0 in the hashed lock; `libgomp1` in the image.

[0.5.0]: https://github.com/the-sudipta/SelfHeal-AirTwin/releases/tag/v0.5.0

## [0.4.0] - 2026-10-31

Docker image, compose and the Kafka + Spark Structured Streaming backend.

### Added

- Multi-stage `Dockerfile`: Python 3.11 and Java 17 base images pinned by digest, hashed dependency install, the four Spark-Kafka connector JARs verified with `ADD --checksum`, datasets downloaded and verified at build time, non-root user, OCI labels, `HEALTHCHECK`, `EXPOSE 8080`. The container runs offline.
- `docker-compose.yml`: `twin` on the memory backend; profile `kafka` with Apache Kafka 4.3.2 (single-node KRaft, pinned by digest) and `twin-kafka` on Kafka + Spark. Results are mounted to `./results`.
- `airtwin.stream.kafka_stream`: readings published as JSON to a fresh topic, read back by Spark Structured Streaming in local mode, reassembled into the same hourly ticks as the memory backend. Full Beijing replay through Kafka + Spark: 35,064 ticks, 420,768 readings.
- `create_stream` factory, `stream.kafka` configuration section with `AIRTWIN_KAFKA_BOOTSTRAP` override, `--backend` option and `check` command.
- CI job that builds the image, runs the health check, replays on both backends and runs a real Kafka + Spark test inside the image.
- PySpark 4.3.0 and confluent-kafka 2.16.1 in the hashed lock.

[0.4.0]: https://github.com/the-sudipta/SelfHeal-AirTwin/releases/tag/v0.4.0

## [0.3.0] - 2026-10-31

Stream interface and in-memory replay backend.

### Added

- `airtwin.stream.interface`: the contract every backend follows. `Reading` (one site, one hour, read-only values, NaN for missing), `Tick` (one twinning cycle with readings sorted by unique site), the runtime-checkable `StreamSource` protocol and `check_order` for strictly increasing time.
- `airtwin.stream.memory_stream`: `MemoryStream`, the default backend, replays a long table as one tick per hour with an optional pause, a tick limit and clean shutdown; `from_wide` adapts the single-site UCI table.
- `stream` section in `configs/default.yaml` (backend, replay pause, UCI site name), validated at start-up.
- `airtwin replay` streams a verified dataset and reports ticks, readings and readings per second. On the real data: UCI 9,357 ticks; Beijing 35,064 ticks with 420,768 readings.

[0.3.0]: https://github.com/the-sudipta/SelfHeal-AirTwin/releases/tag/v0.3.0

## [0.2.0] - 2026-10-30

Verified data download, loaders and cleaning.

### Added

- `configs/default.yaml` and `airtwin.config`: one YAML file loaded into typed, immutable settings with clear errors for missing or mistyped keys.
- Pinned SHA-256 checksums for both UCI archives in `data/checksums.sha256`, and `data/README.md` with licences (CC BY 4.0) and required citations.
- `airtwin.data.download`: download through a temporary file, verification against the pinned checksums, deletion and a hard stop on any mismatch.
- `airtwin.data.uci_loader`: UCI Air Quality read straight from its archive, `-200` turned into NaN, clean column names (reference analyzer vs low-cost sensors), regular hourly index. The real file gives 9,357 consecutive hours.
- `airtwin.data.beijing_loader`: the 12 Beijing station files read from the nested archive (unrelated files ignored), `NA` turned into NaN, one long table sorted by station and time. The real archive gives 420,768 rows, 35,064 hours per station.
- `airtwin` command with `download` and `prepare`.
- Runtime dependencies numpy, pandas and PyYAML in the hashed lock.

[0.2.0]: https://github.com/the-sudipta/SelfHeal-AirTwin/releases/tag/v0.2.0

## [0.1.0] - 2026-10-30

Repository foundation.

### Added

- Repository scaffolding: LF line endings for all text files, ignore rules for data, results and caches, editor settings.
- MIT licence, citation metadata (`CITATION.cff`) and the first root README with problem, contribution and roadmap.
- Contributing guide, code of conduct, security policy and the first version of `INTEGRITY.md` (signed commits and tags, protected `main`, no history rewrites, SHA-pinned CI).
- `pyproject.toml` with ruff, strict mypy, pytest and coverage settings.
- Hashed dependency lock (`requirements.lock`) for Python 3.11, installed with `--require-hashes`.
- `airtwin` package skeleton with a version-consistency test across the package, `pyproject.toml` and `CITATION.cff`.
- CI workflow (ruff, format check, mypy, pytest with coverage), dependabot, issue forms and pull request template.

[0.1.0]: https://github.com/the-sudipta/SelfHeal-AirTwin/releases/tag/v0.1.0
