# `airtwin.experiments`

The reproducible experiments behind every number in the paper: inject known drift, run the twin and the baselines, score them, test the differences, and draw the figures.

| File | What it does |
|---|---|
| `drift_injection.py` | Step, linear and exponential multiplicative drifts with signed magnitudes; seeded planning of which sensors drift and when; injection into a copy of the data |
| `baselines.py` | Linear calibration fitted once or refitted on a rolling window, and a scalar Kalman filter that tracks a sensor's gain against the twin's expected value |
| `metrics.py` | RMSE and MAE with gaps, and detection scoring: detected drifts, delays, false alarms, precision, recall, F1, false alarms per 1,000 sensor-hours |
| `stats.py` | Mean with a t-based 95% confidence interval; paired Wilcoxon signed-rank test with rank-biserial effect size |
| `ablation.py` | The seven variants (full and six with one part removed) and the sensitivity settings as configuration changes |
| `runner.py` | UCI experiment against the reference analyzer; Beijing runs (main, ablation, sensitivity) in parallel with shared, once-trained models; what-if checks, replay capture, throughput; summary tables |
| `report.py` | Figures (Okabe-Ito palette, one font, PNG and SVG without timestamps), the README results block and the replay JSON |
| `verify.py` | Value-by-value comparison of regenerated and reference tables, and `SHA256SUMS` lines |

## How it connects

- Settings come from the `experiments` section of `configs/default.yaml`; the twin itself is used only through `airtwin.twin.engine`.
- `airtwin reproduce`, `airtwin verify` and `airtwin report` in `cli.py` call these modules; outputs go to `results/` (see its README).
- Runs are seeded and every model is deterministic and single-threaded, so a rerun reproduces every table exactly.
