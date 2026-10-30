# SelfHeal-AirTwin

**A self-healing digital twin that detects drift in low-cost urban air-quality sensors, corrects it while data streams in, and tells the city which sensor to recalibrate first.**

[![CI](https://github.com/the-sudipta/SelfHeal-AirTwin/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/the-sudipta/SelfHeal-AirTwin/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> **Status:** under active development. Milestone `v0.1.0` provides the repository foundation (licence, citation, tooling, signed history, CI). Quick start, results and the live twin appear as later milestones land; see [CHANGELOG.md](CHANGELOG.md).

## The problem

Cities fill the gaps between a few expensive reference stations with many low-cost air-quality sensors. These sensors drift: their readings slowly move away from the truth, and nobody notices until decisions have already been made on wrong numbers. Existing big-data air-quality work forecasts pollution well but assumes the sensor data is correct.

## What is new

- **A drift-aware twin per sensor:** a virtual entity predicts the value each sensor *should* read from neighbouring sensors, weather and the reference analyzer, and turns the residual into a smoothed drift score (EWMA and CUSUM).
- **Self-healing in the stream:** once drift is confirmed, the twin estimates an offset and gain correction online and publishes corrected values.
- **Feedback to the physical network:** a ranked maintenance list says which sensor to recalibrate first and why, and a what-if module shows how error grows if a sensor is left uncorrected. This closed loop is what makes the system a digital twin rather than a digital shadow.

## Why it matters

Air-quality alerts, traffic restrictions and health advice are only as good as the sensor data behind them. Catching and correcting drift automatically keeps low-cost networks trustworthy at a fraction of the cost of constant manual calibration.

## Data

Two public datasets from the UCI Machine Learning Repository: [Air Quality](https://archive.ics.uci.edu/dataset/360/air+quality) (real sensor drift with a co-located reference analyzer) and [Beijing Multi-Site Air Quality](https://archive.ics.uci.edu/dataset/501) (12 sites, hourly, 2013–2017, used for controlled drift-injection experiments).

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
