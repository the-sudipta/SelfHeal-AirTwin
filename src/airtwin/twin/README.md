# `airtwin.twin`

The digital twin itself: a virtual copy of every sensor that knows what the sensor should read, notices when it drifts, corrects it, and tells the city which sensor to service first.

| File | What it does |
|---|---|
| `state.py` | The shared vocabulary: `SensorKey` (`site:variable`), `SensorStatus` (warm-up, healthy, watch, drifting, healed), `Correction` (offset and gain), `SensorState` (raw, expected, residual, drift score, status, corrected value) and the frozen hourly `TwinSnapshot` |
| `expected_model.py` | The virtual entity: one deterministic LightGBM regressor per sensor predicts its expected value from neighbouring sites, local weather, the reference analyzer and the hour of day; `ExpectedValueBank` learns from the calibration window and then predicts every hour |
| `drift_detector.py` | Learns each sensor's normal residual level and spread in a baseline window, smooths the residual with a 24-hour rolling median (pollution episodes last hours, drift lasts days), and runs EWMA and two-sided CUSUM with limits measured on the baseline, because air-quality residuals are autocorrelated; one drift score (1.0 = alarm line) drives healthy, watch and drifting, with confirmation after consecutive alarm hours |

## How it connects

- Input is one `Tick` per hour from `airtwin.stream`; `flatten` turns it into a `site:variable` row.
- Which sensors are twinned, their calibration window (one year for Beijing so every season is seen, 30 days for UCI), which inputs their models may use, the LightGBM settings and the drift detector settings come from the `twin` section of `configs/default.yaml`; the `use_*` switches also drive the ablation study.
- A sensor's own reading is never an input of its model, so drift cannot leak into the expected value.
- Self-healing, feedback, what-if and `engine.py` (the only module that wires the parts together) follow in the next milestones and work on `TwinSnapshot`; the self-healer resets a sensor's detector once its correction is active.
