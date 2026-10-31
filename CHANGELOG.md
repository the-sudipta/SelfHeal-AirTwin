# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

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
