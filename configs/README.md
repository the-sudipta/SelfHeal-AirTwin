# Configuration

The single YAML file that holds every tunable value of the project; code contains no magic numbers.

| File | What it does |
|---|---|
| `default.yaml` | Data paths, dataset URLs and archive names, download timeout, missing-value markers (`data`); stream backend, replay pause and the UCI site name (`stream`); broker address, topic prefix and Spark settings (`stream.kafka`); LightGBM parameters and, per dataset, the calibration window, twinned variables and allowed model inputs (`twin`); baseline window, residual smoothing, EWMA and CUSUM parameters, watch level and confirmation hours (`twin.drift`), chosen on years 1–2 of Beijing only; correction fit window, gain rules, bounds and acceptance thresholds (`twin.heal`); maintenance-list threshold and duration weight (`twin.feedback`); what-if horizons and history (`twin.what_if`); the `trust_substitution` switch. Later milestones add experiment and API settings |

## How it connects

- `src/airtwin/config.py` loads this file into frozen, typed dataclasses and fails with a clear message when a key is missing or has the wrong type.
- Relative paths are resolved against the project root, which is the parent of this folder, so the same file works on Windows, in CI and in the container.
- To run with a different file, set the `AIRTWIN_CONFIG` environment variable to its path; `AIRTWIN_KAFKA_BOOTSTRAP` overrides the Kafka broker address.
