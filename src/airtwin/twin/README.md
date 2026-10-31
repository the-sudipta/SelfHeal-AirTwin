# `airtwin.twin`

The digital twin itself: a virtual copy of every sensor that knows what the sensor should read, notices when it drifts, corrects it, and tells the city which sensor to service first.

| File | What it does |
|---|---|
| `state.py` | The shared vocabulary: `SensorKey` (`site:variable`), `SensorStatus` (warm-up, healthy, watch, drifting, healed), `Correction` (offset and gain), `SensorState` (raw, expected, residual, drift score, status, corrected value) and the frozen hourly `TwinSnapshot` |
| `expected_model.py` | The virtual entity: one deterministic LightGBM regressor per sensor predicts its expected value from neighbouring sites, local weather, the reference analyzer and the hour of day; `ExpectedValueBank` learns from the calibration window and then predicts every hour |
| `drift_detector.py` | Learns each sensor's normal residual level and spread in a baseline window, smooths the residual with a 24-hour rolling median (pollution episodes last hours, drift lasts days), and runs EWMA and two-sided CUSUM with limits measured on the baseline, because air-quality residuals are autocorrelated; one drift score (1.0 = alarm line) drives healthy, watch and drifting, with confirmation after consecutive alarm hours |
| `self_healer.py` | On confirmed drift, fits `raw = gain * expected + offset` robustly on the pairs since the drift began (offset only until enough days for a gain), proposes it with its evidence (relative effect, residual improvement), publishes `(raw - offset) / gain` once accepted, and refits daily while active so a growing drift stays corrected |
| `feedback.py` | The maintenance list sent to the city: sensors ranked by relative error × (1 + days faulty / weight), each with a one-line reason |
| `what_if.py` | Projects a sensor's relative error 7, 14 and 30 days ahead from the trend of its recent corrections |
| `engine.py` | The only module that wires the parts: every hour expected value → correction → drift detection on the corrected residual → healing → events; a correction is applied only if it is large, clearly better and points the right way (otherwise the alarm is dismissed) and is retired once the shift is gone; adds trust substitution (untrusted neighbours enter other models as their virtual value) and fault isolation (dependents of a newly confirmed sensor restart their drift evidence); maintenance list, what-if and mark-recalibrated |

## How it connects

- Input is one `Tick` per hour from `airtwin.stream`; `flatten` turns it into a `site:variable` row.
- Which sensors are twinned, their calibration window (one year for Beijing so every season is seen, 30 days for UCI), which inputs their models may use, the LightGBM settings and the drift detector settings come from the `twin` section of `configs/default.yaml`; the `use_*` switches also drive the ablation study.
- A sensor's own reading is never an input of its model, so drift cannot leak into the expected value.
- `engine.py` is the only module that imports the other parts; the API and the experiments call the engine and never the parts directly.
- The feedback loop closes when `mark_recalibrated` is called for a serviced sensor: its correction, drift evidence and what-if history are cleared.
