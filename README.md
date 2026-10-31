# SelfHeal-AirTwin

**A self-healing digital twin that detects drift in low-cost urban air-quality sensors, corrects it while data streams in, and tells the city which sensor to recalibrate first.**

[![CI](https://github.com/the-sudipta/SelfHeal-AirTwin/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/the-sudipta/SelfHeal-AirTwin/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> **Status:** under active development. Milestone `v0.7.0` closes the twin loop: self-healing corrections, the ranked maintenance list, what-if projections and the engine, on top of drift detection, the expected-value model, verified data, both stream backends and the Docker image. Results and the live twin appear as later milestones land; see [CHANGELOG.md](CHANGELOG.md).

## The problem

Cities fill the gaps between a few expensive reference stations with many low-cost air-quality sensors. These sensors drift: their readings slowly move away from the truth, and nobody notices until decisions have already been made on wrong numbers. Existing big-data air-quality work forecasts pollution well but assumes the sensor data is correct.

## What is new

- **A drift-aware twin per sensor:** a virtual entity predicts the value each sensor *should* read from neighbouring sensors, weather and the reference analyzer, and turns the residual into a smoothed drift score (EWMA and CUSUM).
- **Self-healing in the stream:** once drift is confirmed, the twin estimates an offset and gain correction online and publishes corrected values.
- **Feedback to the physical network:** a ranked maintenance list says which sensor to recalibrate first and why, and a what-if module shows how error grows if a sensor is left uncorrected. This closed loop is what makes the system a digital twin rather than a digital shadow.

## Why it matters

Air-quality alerts, traffic restrictions and health advice are only as good as the sensor data behind them. Catching and correcting drift automatically keeps low-cost networks trustworthy at a fraction of the cost of constant manual calibration.

## Quick start

Install only [Docker](https://docs.docker.com/get-docker/). The image downloads both datasets during the build, verifies their SHA-256 checksums and then runs fully offline.

```powershell
docker compose up                    # the twin on the in-memory stream backend
docker compose --profile kafka up    # adds Apache Kafka (KRaft) and runs the twin on Kafka + Spark Structured Streaming
docker compose run --rm twin reproduce   # reruns every experiment, rewrites results/, then verifies against the reference
```

At this milestone both services replay the Beijing dataset hour by hour through their backend and print ticks, readings and readings per second. `reproduce` takes about 40 minutes on a laptop and ends with `PASS` when every regenerated table matches the committed reference. The live web twin at `http://localhost:8080` arrives with a later milestone. Generated outputs land in `./results` on your own disk.

## Data

Two public datasets from the UCI Machine Learning Repository: [Air Quality](https://archive.ics.uci.edu/dataset/360/air+quality) (real sensor drift with a co-located reference analyzer) and [Beijing Multi-Site Air Quality](https://archive.ics.uci.edu/dataset/501) (12 sites, hourly, 2013–2017, used for controlled drift-injection experiments). Both are licensed CC BY 4.0; provenance, checksums and required citations are in [data/README.md](data/README.md).

Without Docker, fetch, verify and clean both datasets (Windows PowerShell, inside the virtual environment from [CONTRIBUTING.md](CONTRIBUTING.md)):

```powershell
$env:PYTHONPATH = "src"
python -m airtwin.cli download   # downloads both archives and checks their SHA-256
python -m airtwin.cli prepare    # writes cleaned hourly tables to data/processed/
python -m airtwin.cli replay     # streams Beijing hour by hour and reports readings per second
```

## Results

<!-- results:start -->
### UCI Air Quality (real drift): RMSE against the reference analyzer

| Sensor | Raw | One-time calibration | Rolling recalibration | Kalman gain tracking | SelfHeal-AirTwin |
|---|---|---|---|---|---|
| s1_co | 0.86 | 1.13 | 0.70 | 0.73 | 0.72 |
| s2_nmhc | 1.45 | 1.46 | 1.61 | 1.65 | 1.46 |
| s3_nox | 194.09 | 186.92 | 162.21 | 214.60 | 221.57 |
| s4_no2 | 62.95 | 59.11 | 32.80 | 38.75 | 39.35 |

### Beijing PM2.5 (injected drift, years 3-4): detection, mean over runs

| Drift | Runs | Recall | Precision | False alarms / 1,000 h | Median delay (h) |
|---|---|---|---|---|---|
| exponential | 30 | 1.00 | 0.03 | 0.56 | 1268 |
| linear | 30 | 1.00 | 0.03 | 0.49 | 742 |
| step | 30 | 1.00 | 0.03 | 0.52 | 150 |

### Beijing PM2.5: RMSE of published values, drifting sensors (µg/m³, mean [95% CI])

| Drift | Raw | One-time calibration | Rolling recalibration | Kalman gain tracking | SelfHeal-AirTwin |
|---|---|---|---|---|---|
| exponential | 35.8 [34.0, 37.6] | 33.5 [31.3, 35.8] | 18.4 [17.1, 19.6] | 13.2 [12.1, 14.3] | 19.1 [17.4, 20.9] |
| linear | 39.5 [37.3, 41.7] | 37.9 [35.6, 40.1] | 17.8 [16.6, 19.1] | 13.4 [12.0, 14.8] | 17.1 [15.3, 18.9] |
| step | 39.9 [37.6, 42.1] | 38.2 [35.6, 40.8] | 18.0 [16.8, 19.2] | 13.4 [12.2, 14.5] | 17.6 [15.8, 19.4] |

### Beijing PM2.5: RMSE of published values, healthy sensors (µg/m³, mean [95% CI])

| Drift | Raw | One-time calibration | Rolling recalibration | Kalman gain tracking | SelfHeal-AirTwin |
|---|---|---|---|---|---|
| exponential | 0.0 [0.0, 0.0] | 6.4 [6.2, 6.6] | 17.0 [16.3, 17.7] | 12.6 [12.0, 13.2] | 4.0 [3.5, 4.5] |
| linear | 0.0 [0.0, 0.0] | 6.6 [6.5, 6.8] | 17.6 [17.0, 18.2] | 12.9 [12.3, 13.4] | 3.4 [3.1, 3.7] |
| step | 0.0 [0.0, 0.0] | 6.6 [6.5, 6.8] | 17.6 [16.7, 18.5] | 13.0 [12.3, 13.8] | 3.6 [3.2, 3.9] |

### Beijing PM2.5: RMSE of published values, all sensors (µg/m³, mean [95% CI])

| Drift | Raw | One-time calibration | Rolling recalibration | Kalman gain tracking | SelfHeal-AirTwin |
|---|---|---|---|---|---|
| exponential | 7.2 [6.8, 7.7] | 11.6 [11.2, 12.1] | 17.1 [16.6, 17.5] | 12.5 [12.1, 12.9] | 6.9 [6.3, 7.5] |
| linear | 7.7 [7.2, 8.2] | 12.5 [11.9, 13.0] | 17.4 [16.9, 17.8] | 12.7 [12.3, 13.2] | 5.9 [5.5, 6.4] |
| step | 7.7 [7.2, 8.3] | 12.5 [11.9, 13.0] | 17.4 [16.8, 17.9] | 12.7 [12.2, 13.3] | 6.2 [5.7, 6.6] |

### Ablation (mean over runs)

| Variant | F1 | False alarms / 1,000 h | RMSE drifted | RMSE healthy | RMSE all |
|---|---|---|---|---|---|
| cusum_only | 0.06 | 0.49 | 17.8 | 3.6 | 6.3 |
| ewma_only | 0.59 | 0.02 | 22.2 | 0.9 | 5.1 |
| full | 0.06 | 0.49 | 17.8 | 3.6 | 6.3 |
| no_neighbours | 0.01 | 2.65 | 61.9 | 55.3 | 56.5 |
| no_self_healing | 0.06 | 0.47 | 37.6 | 0.0 | 7.4 |
| no_trust_substitution | 0.02 | 1.72 | 17.5 | 8.5 | 10.0 |
| no_weather | 0.06 | 0.52 | 17.1 | 3.2 | 5.9 |

All numbers are produced by `airtwin reproduce`; statistics, figures and the full tables are listed in [results/README.md](results/README.md).
<!-- results:end -->

## Roadmap

| Release | Content |
|---|---|
| v0.1.0 | Repository foundation, signed history, CI |
| v0.2.0 | Verified data download, loaders, cleaning |
| v0.3.0 | Stream interface and in-memory backend |
| v0.4.0 | Docker image, Kafka and Spark backend |
| v0.5.0 – v0.7.0 | Twin state, expected-value model, drift detector, self-healer, feedback, what-if |
| v0.8.0 | Experiments, baselines, statistics, verification |
| v0.9.0 | API and interactive web twin |
| v0.10.0 | Visuals, project site, release automation |
| v1.0.0 | Full reproduction run and final results |

## Licence and citation

Released under the [MIT License](LICENSE). If you use this software, please cite it using [CITATION.cff](CITATION.cff).
