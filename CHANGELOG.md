# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

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
