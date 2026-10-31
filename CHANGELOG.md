# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

## [0.9.0] - 2026-10-31

The live twin: API and interactive web twin.

### Added

- `airtwin serve` (now the container's default command): the live twin and the web twin at `http://localhost:8080`; with the `kafka` profile the same twin runs on Kafka + Spark at port 8081.
- `airtwin.api`: a background run that replays the calibration year and the drift baseline at full speed and then one hour of Beijing data per second; REST endpoints for state, history, maintenance list, events and what-if; Server-Sent Events with one update per hour, resumable after a reconnect; commands to pause, inject a labelled demonstration drift and mark a sensor recalibrated. The network error of raw and published values is measured against the original readings. Docs at `/api/docs`.
- `web/`: the interactive 3D Beijing twin (plain HTML, CSS, ES modules and SVG, no build step, no external downloads): ring roads, landmarks and buildings; site pins with readings rising to the Twin Core and corrections flying back; the "What is happening now" story (watch, detect, heal, feedback); site panel with raw, expected and corrected values, 48-hour chart and drift score; maintenance list with "Mark recalibrated"; event log; what-if slider. Keyboard access, visible focus, reduced motion and phone layout.
- `airtwin.data.datasets`: loads either dataset by name for the CLI and the API.
- `api` configuration section.
- CI starts the live twin on both backends and checks the API, the page and a command.

### Changed

- `TwinEngine.what_if()` accepts any horizon (the experiments keep 7, 14 and 30 days).

### Fixed

- The Kafka stream no longer counts the time its consumer spends on ticks (a paced or paused twin) as Kafka idle time, which could stop a slow consumer with an idle-timeout error.

[0.9.0]: https://github.com/the-sudipta/SelfHeal-AirTwin/releases/tag/v0.9.0

## [0.8.0] - 2026-10-31

The experiments: every result in the paper from one command.

### Added

- `airtwin.experiments.drift_injection`: step, linear and exponential multiplicative drifts with signed sizes, injected into chosen sensors from a seeded plan.
- `airtwin.experiments.metrics`: RMSE, MAE and detection scoring (delay, precision, recall, F1, false alarms per 1,000 sensor-hours).
- `airtwin.experiments.stats`: mean with t-based 95 % confidence interval; paired Wilcoxon signed-rank test with rank-biserial effect size.
- `airtwin.experiments.baselines`: one-time calibration, rolling linear recalibration and Kalman-filter gain tracking.
- `airtwin.experiments.ablation`: seven variants (full, no neighbours, no weather, EWMA only, CUSUM only, no self-healing, no trust substitution) and the threshold and EWMA sensitivity settings.
- `airtwin.experiments.runner`, `report` and `verify`: UCI and Beijing runs on parallel worker processes, tables, figures (PNG and SVG), the README results block, the web-twin replay file and value-by-value verification.
- `airtwin reproduce` (`--smoke`, `--kafka`, `--update-reference`), `airtwin verify` and `airtwin report`.
- Reference tables in `results/reference/full` and `results/reference/smoke`, `results/SHA256SUMS`, and `site/data/replay.json`.
- CI runs `reproduce --smoke` in the Docker image on every push.
- `experiments` configuration section; `twin.heal.enabled`; `twin.what_if.min_trend_r2`.

### Changed

- The engine accepts a shared, already calibrated model bank; with healing disabled the detector restarts after each alarm.
- What-if uses the trend of recent corrections only when it explains at least half of their variation (R² ≥ 0.5); otherwise it holds the current error.
- SciPy and Matplotlib added to the locked dependencies.

### Results (full run, 370 runs)

- Beijing PM2.5, 30 seeds per drift type: all 270 injected drifts detected; median delay 150 h (step), 742 h (linear), 1,268 h (exponential); 0.49–0.56 false alarms per 1,000 sensor-hours. RMSE over all sensors is the lowest of all methods for every drift type (5.9–6.9 µg/m³ against 7.2–17.4).
- UCI Air Quality (real drift): better than one-time calibration for CO and NO₂, equal for benzene, worse for NOx.
- Throughput: about 11,000 readings per second on the memory backend (machine-dependent).

[0.8.0]: https://github.com/the-sudipta/SelfHeal-AirTwin/releases/tag/v0.8.0

## [0.7.0] - 2026-10-31

The closed loop: self-healing, maintenance feedback, what-if and the twin engine.

### Added

- `airtwin.twin.self_healer`: on confirmed drift, a robust fit of `raw = gain * expected + offset` on the pairs since the drift began (offset only until 72 pairs, then gain and offset), proposed with its evidence and refitted daily while active.
- `airtwin.twin.feedback`: the maintenance list — sensors ranked by relative error × (1 + days faulty / 7), each with a one-line reason.
- `airtwin.twin.what_if`: projection of a sensor's relative error 7, 14 and 30 days ahead from the trend of its recent corrections.
- `airtwin.twin.engine`: the only module that wires the twin parts, with
  - **trust substitution**: a sensor with confirmed drift or a correction enters its neighbours' models as its virtual value, so it cannot mislead them;
  - **fault isolation**: when a sensor is confirmed, its dependants restart their drift evidence;
  - **correction guards**: a correction is applied only if it changes readings by at least 10 %, cuts the residual by at least 30 % and agrees with the alarm's direction; otherwise the alarm is dismissed. Corrections are retired once the shift is gone;
  - events (calibrated, watch, detect, heal, refit, dismissed, recovered, recalibrated) and `mark_recalibrated` for serviced sensors.
- `airtwin twin`: runs the twin over a dataset and prints events, the maintenance list and a what-if.
- `twin.heal`, `twin.feedback`, `twin.what_if` and `twin.trust_substitution` configuration.

### Evidence (development runs, not final results)

- Four years of Beijing, calibration year 1: corrections on healthy stations 1.08 per 1,000 hours per sensor (11,213 → 1,997 thanks to the guards); 8 of 72 sensors corrected at the end. An injected +30 % PM2.5 drift at Dongsi was confirmed after 43 hours, corrected to a final gain of 1.337 (true 1.30) and ranked first, with no extra alarms at the other PM2.5 sites.
- UCI Air Quality: the maintenance list ends with S3 (NOx, −30 %) and S4 (NO₂, −22 %).
- Open: residual false corrections, many confirmations on UCI (30-day calibration), what-if stability — to be quantified in the experiments.

[0.7.0]: https://github.com/the-sudipta/SelfHeal-AirTwin/releases/tag/v0.7.0

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
