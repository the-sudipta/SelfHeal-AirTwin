# `airtwin.data`

Gets the two public datasets onto disk, proves they are the published files, and turns them into clean hourly tables.

| File | What it does |
|---|---|
| `download.py` | Downloads each archive through a temporary file, checks it against `data/checksums.sha256`, deletes it and stops on any mismatch; `verify_all` re-checks files already on disk |
| `uci_loader.py` | Reads `AirQualityUCI.csv` from its archive (semicolons, decimal commas), builds timestamps, turns `-200` into NaN, renames columns (`*_ref` = reference analyzer, `s*_` = low-cost sensors) and regularises to hourly |
| `beijing_loader.py` | Reads the 12 station CSVs from the nested archive, ignores unrelated files, turns `NA` into NaN, builds timestamps and returns one long table sorted by station and time |

## How it connects

- Settings (URLs, file names, missing-value markers, timeout) come from `configs/default.yaml` through `airtwin.config`.
- `airtwin download` and `airtwin prepare` in `cli.py` call these modules; cleaned tables go to `data/processed/`.
- The stream backends in `airtwin.stream` (next milestone) replay these cleaned tables hour by hour.
- Original archives are never modified or unpacked to disk.
