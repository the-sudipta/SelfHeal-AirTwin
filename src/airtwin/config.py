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
    kafka: KafkaConfig


@dataclass(frozen=True)
class KafkaConfig:
    """Connection and Spark settings of the Kafka + Spark Structured Streaming backend."""

    bootstrap_servers: str
    topic_prefix: str
    spark_master: str
    spark_driver_memory: str
    spark_jars_dir: Path
    max_offsets_per_trigger: int
    poll_timeout_s: float
    idle_timeout_s: float


@dataclass(frozen=True)
class ModelParams:
    """Hyper-parameters of the per-sensor LightGBM expected-value model."""

    n_estimators: int
    learning_rate: float
    num_leaves: int
    min_data_in_leaf: int
    seed: int


@dataclass(frozen=True)
class TargetSpec:
    """Which sensors of one dataset get a twin, and which inputs their models may use."""

    variables: tuple[str, ...]
    weather: tuple[str, ...]
    reference: tuple[str, ...]
    use_neighbours: bool
    use_weather: bool
    use_reference: bool
    use_time: bool


@dataclass(frozen=True)
class TwinConfig:
    """Settings of the twin's virtual entity."""

    calibration_hours: int
    min_training_rows: int
    model: ModelParams
    targets: Mapping[str, TargetSpec]

    def target(self, dataset: str) -> TargetSpec:
        """Return the target settings of one dataset."""
        try:
            return self.targets[dataset]
        except KeyError as exc:
            raise ConfigError(f"no twin targets for dataset {dataset!r}") from exc


@dataclass(frozen=True)
class Config:
    """The complete project configuration."""

    root: Path
    data: DataConfig
    stream: StreamConfig
    twin: TwinConfig


def _require(section: Mapping[str, Any], key: str, kind: type, where: str) -> Any:
    """Return ``section[key]`` after checking that it exists and has the expected type."""
    if key not in section:
        raise ConfigError(f"missing key {where}.{key}")
    value = section[key]
    accepted: tuple[type, ...] = (int, float) if kind is float else (kind,)
    if (isinstance(value, bool) and kind is not bool) or not isinstance(value, accepted):
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
KAFKA_BOOTSTRAP_ENV_VAR = "AIRTWIN_KAFKA_BOOTSTRAP"


def _parse_kafka(raw: Mapping[str, Any], root: Path) -> KafkaConfig:
    """Build the Kafka subsection; ``AIRTWIN_KAFKA_BOOTSTRAP`` overrides the broker address."""
    where = "stream.kafka"
    positive = {
        "max_offsets_per_trigger": int(_require(raw, "max_offsets_per_trigger", int, where)),
        "poll_timeout_s": float(_require(raw, "poll_timeout_s", float, where)),
        "idle_timeout_s": float(_require(raw, "idle_timeout_s", float, where)),
    }
    for key, value in positive.items():
        if value <= 0:
            raise ConfigError(f"{where}.{key} must be positive")
    bootstrap = _require(raw, "bootstrap_servers", str, where)
    return KafkaConfig(
        bootstrap_servers=os.environ.get(KAFKA_BOOTSTRAP_ENV_VAR, bootstrap),
        topic_prefix=_require(raw, "topic_prefix", str, where),
        spark_master=_require(raw, "spark_master", str, where),
        spark_driver_memory=_require(raw, "spark_driver_memory", str, where),
        spark_jars_dir=root / _require(raw, "spark_jars_dir", str, where),
        max_offsets_per_trigger=int(positive["max_offsets_per_trigger"]),
        poll_timeout_s=positive["poll_timeout_s"],
        idle_timeout_s=positive["idle_timeout_s"],
    )


def _parse_stream(raw: Mapping[str, Any], root: Path) -> StreamConfig:
    """Build the stream section and check the backend name and delay."""
    backend = _require(raw, "backend", str, "stream")
    if backend not in STREAM_BACKENDS:
        raise ConfigError(f"stream.backend must be one of {STREAM_BACKENDS}, got {backend!r}")
    delay = float(_require(raw, "replay_delay_s", float, "stream"))
    if delay < 0:
        raise ConfigError("stream.replay_delay_s must not be negative")
    return StreamConfig(
        backend=backend,
        replay_delay_s=delay,
        uci_site=_require(raw, "uci_site", str, "stream"),
        kafka=_parse_kafka(_require(raw, "kafka", dict, "stream"), root),
    )


def _names(raw: Mapping[str, Any], key: str, where: str) -> tuple[str, ...]:
    """Read a list of column names."""
    values = _require(raw, key, list, where)
    if not all(isinstance(v, str) and v for v in values):
        raise ConfigError(f"{where}.{key} must be a list of names")
    return tuple(values)


def _positive_int(raw: Mapping[str, Any], key: str, where: str) -> int:
    """Read an integer that must be at least 1."""
    value = int(_require(raw, key, int, where))
    if value < 1:
        raise ConfigError(f"{where}.{key} must be at least 1")
    return value


def _parse_twin(raw: Mapping[str, Any]) -> TwinConfig:
    """Build the twin section: calibration window, model parameters and per-dataset targets."""
    model_raw = _require(raw, "model", dict, "twin")
    learning_rate = float(_require(model_raw, "learning_rate", float, "twin.model"))
    if not 0 < learning_rate <= 1:
        raise ConfigError("twin.model.learning_rate must be in (0, 1]")
    model = ModelParams(
        n_estimators=_positive_int(model_raw, "n_estimators", "twin.model"),
        learning_rate=learning_rate,
        num_leaves=_positive_int(model_raw, "num_leaves", "twin.model"),
        min_data_in_leaf=_positive_int(model_raw, "min_data_in_leaf", "twin.model"),
        seed=int(_require(model_raw, "seed", int, "twin.model")),
    )
    targets = {}
    for name, entry in _require(raw, "targets", dict, "twin").items():
        where = f"twin.targets.{name}"
        variables = _names(entry, "variables", where)
        if not variables:
            raise ConfigError(f"{where}.variables must not be empty")
        targets[name] = TargetSpec(
            variables=variables,
            weather=_names(entry, "weather", where),
            reference=_names(entry, "reference", where),
            use_neighbours=_require(entry, "use_neighbours", bool, where),
            use_weather=_require(entry, "use_weather", bool, where),
            use_reference=_require(entry, "use_reference", bool, where),
            use_time=_require(entry, "use_time", bool, where),
        )
    return TwinConfig(
        calibration_hours=_positive_int(raw, "calibration_hours", "twin"),
        min_training_rows=_positive_int(raw, "min_training_rows", "twin"),
        model=model,
        targets=targets,
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
        stream=_parse_stream(_require(raw, "stream", dict, "config"), root),
        twin=_parse_twin(_require(raw, "twin", dict, "config")),
    )
