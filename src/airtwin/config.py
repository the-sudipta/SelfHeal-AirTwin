"""Load the YAML configuration into typed, immutable settings objects."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_ENV_VAR = "AIRTWIN_CONFIG"
DEFAULT_CONFIG = Path("configs") / "default.yaml"


class ConfigError(ValueError):
    """Raised when the configuration file is missing a key or has a wrong type."""


@dataclass(frozen=True)
class DatasetConfig:
    """Where one dataset comes from and where its files are stored."""

    name: str
    url: str
    archive: str
    processed: str


@dataclass(frozen=True)
class DataConfig:
    """Paths and parsing settings for the raw and processed datasets."""

    raw_dir: Path
    processed_dir: Path
    checksums_file: Path
    download_timeout_s: float
    datasets: Mapping[str, DatasetConfig]
    uci_missing_value: float
    beijing_missing_token: str

    def dataset(self, name: str) -> DatasetConfig:
        """Return the settings of one dataset by its configuration key."""
        try:
            return self.datasets[name]
        except KeyError as exc:
            raise ConfigError(f"unknown dataset {name!r}") from exc


@dataclass(frozen=True)
class StreamConfig:
    """Which stream backend replays the data, and how fast."""

    backend: str
    replay_delay_s: float
    uci_site: str


@dataclass(frozen=True)
class Config:
    """The complete project configuration."""

    root: Path
    data: DataConfig
    stream: StreamConfig


def _require(section: Mapping[str, Any], key: str, kind: type, where: str) -> Any:
    """Return ``section[key]`` after checking that it exists and has the expected type."""
    if key not in section:
        raise ConfigError(f"missing key {where}.{key}")
    value = section[key]
    accepted: tuple[type, ...] = (int, float) if kind is float else (kind,)
    if isinstance(value, bool) or not isinstance(value, accepted):
        raise ConfigError(f"{where}.{key} must be {kind.__name__}, got {type(value).__name__}")
    return value


def _parse_data(raw: Mapping[str, Any], root: Path) -> DataConfig:
    """Build the data section, resolving relative paths against the project root."""
    datasets_raw = _require(raw, "datasets", dict, "data")
    datasets = {
        name: DatasetConfig(
            name=name,
            url=_require(entry, "url", str, f"data.datasets.{name}"),
            archive=_require(entry, "archive", str, f"data.datasets.{name}"),
            processed=_require(entry, "processed", str, f"data.datasets.{name}"),
        )
        for name, entry in datasets_raw.items()
    }
    return DataConfig(
        raw_dir=root / _require(raw, "raw_dir", str, "data"),
        processed_dir=root / _require(raw, "processed_dir", str, "data"),
        checksums_file=root / _require(raw, "checksums_file", str, "data"),
        download_timeout_s=float(_require(raw, "download_timeout_s", float, "data")),
        datasets=datasets,
        uci_missing_value=float(_require(raw, "uci_missing_value", float, "data")),
        beijing_missing_token=_require(raw, "beijing_missing_token", str, "data"),
    )


STREAM_BACKENDS = ("memory", "kafka")


def _parse_stream(raw: Mapping[str, Any]) -> StreamConfig:
    """Build the stream section and check the backend name and delay."""
    backend = _require(raw, "backend", str, "stream")
    if backend not in STREAM_BACKENDS:
        raise ConfigError(f"stream.backend must be one of {STREAM_BACKENDS}, got {backend!r}")
    delay = float(_require(raw, "replay_delay_s", float, "stream"))
    if delay < 0:
        raise ConfigError("stream.replay_delay_s must not be negative")
    return StreamConfig(
        backend=backend, replay_delay_s=delay, uci_site=_require(raw, "uci_site", str, "stream")
    )


def default_config_path() -> Path:
    """Return the config path from ``AIRTWIN_CONFIG`` or ``configs/default.yaml`` in the cwd."""
    return Path(os.environ.get(CONFIG_ENV_VAR, DEFAULT_CONFIG)).resolve()


def load_config(path: Path | None = None) -> Config:
    """Read and validate a YAML configuration file.

    Args:
        path: The YAML file. Defaults to :func:`default_config_path`.

    Returns:
        The parsed configuration. The project root is the parent of the file's folder.

    Raises:
        ConfigError: If the file is missing, is not a mapping, or lacks a required key.
    """
    path = (path or default_config_path()).resolve()
    if not path.is_file():
        raise ConfigError(f"configuration file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"configuration file is not a mapping: {path}")
    root = path.parent.parent
    return Config(
        root=root,
        data=_parse_data(_require(raw, "data", dict, "config"), root),
        stream=_parse_stream(_require(raw, "stream", dict, "config")),
    )
