# Results

Outputs of `airtwin reproduce`. Everything here is generated; only this file, `SHA256SUMS` and the reference tables in `reference/` are tracked by Git.

| Path | Made by | Content |
|---|---|---|
| `tables/uci_methods.csv` | `airtwin reproduce` | UCI Air Quality: RMSE and MAE against the reference analyzer for each sensor and method (raw, one-time calibration, rolling recalibration, Kalman gain tracking, SelfHeal-AirTwin) |
| `stats/uci_wilcoxon.csv` | `airtwin reproduce` | UCI: paired Wilcoxon signed-rank tests over days, SelfHeal-AirTwin against each baseline, with rank-biserial effect size |
| `tables/beijing_runs.csv` | `airtwin reproduce` | Beijing: one row per run (drift type, seed, variant, sensitivity setting) with detection metrics and RMSE of every method |
| `tables/beijing_detection.csv` | `airtwin reproduce` | Beijing: precision, recall, F1, false alarms per 1,000 sensor-hours and median delay per drift type, mean and 95% CI over seeds |
| `tables/beijing_methods.csv` | `airtwin reproduce` | Beijing: RMSE of published values on drifting and on healthy sensors per drift type and method, mean and 95% CI |
| `stats/beijing_wilcoxon.csv` | `airtwin reproduce` | Beijing: paired Wilcoxon tests over seeds, SelfHeal-AirTwin against each baseline |
| `tables/ablation.csv` | `airtwin reproduce` | Ablation: each variant with one part removed, mean and 95% CI |
| `stats/ablation_wilcoxon.csv` | `airtwin reproduce` | Ablation: paired tests, full twin against each variant (RMSE and F1) |
| `tables/sensitivity.csv` | `airtwin reproduce` | Sensitivity: alarm-threshold scale and EWMA smoothing factor sweeps |
| `tables/what_if.csv` | `airtwin reproduce` | What-if: projected against actual relative error 7, 14 and 30 days after the check |
| `benchmark/throughput.csv` | `airtwin reproduce` (`--kafka` adds the Kafka + Spark backend) | Readings per second and milliseconds per hourly cycle; machine-dependent, so not verified |
| `figures/*.png`, `figures/*.svg` | `airtwin report` (called by `reproduce`) | UCI RMSE, Beijing RMSE, detection delay, ablation, sensitivity and what-if figures (300 dpi PNG and SVG) |
| `replay.json` | `airtwin reproduce` | Thirty days of the twin around an injected drift, replayed by the web twin (copied to `site/data/replay.json` by `report`) |
| `SHA256SUMS` | `airtwin reproduce` | SHA-256 of every table, figure and the replay |
| `reference/full/`, `reference/smoke/` | `airtwin reproduce --update-reference` | Reference tables that `airtwin verify` compares with, value by value |
| `smoke/` | `airtwin reproduce --smoke` | The small seeded slice run by CI |

## How it connects

- Settings of every experiment are in the `experiments` section of `configs/default.yaml`; the code is in `src/airtwin/experiments/`.
- `airtwin verify` checks the dataset checksums and compares the regenerated tables with `reference/` within an absolute tolerance of 1e-6, printing PASS or every difference.
- After the milestone runs, the final tables and figures are attached to the GitHub Release.
