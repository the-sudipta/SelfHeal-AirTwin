# Configuration

The single YAML file that holds every tunable value of the project; code contains no magic numbers.

| File | What it does |
|---|---|
| `default.yaml` | Data paths, dataset URLs and archive names, download timeout, missing-value markers. Later milestones add stream, twin, experiment and API sections |

## How it connects

- `src/airtwin/config.py` loads this file into frozen, typed dataclasses and fails with a clear message when a key is missing or has the wrong type.
- Relative paths are resolved against the project root, which is the parent of this folder, so the same file works on Windows, in CI and in the container.
- To run with a different file, set the `AIRTWIN_CONFIG` environment variable to its path.
