"""Load the YAML configuration into typed, immutable settings objects."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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
    """Which sensors of one dataset get a twin, how long they calibrate, and their model inputs."""

    calibration_hours: int
    variables: tuple[str, ...]
    weather: tuple[str, ...]
    reference: tuple[str, ...]
    use_neighbours: bool
    use_weather: bool
    use_reference: bool
    use_time: bool


DRIFT_METHODS = ("both", "ewma", "cusum")


@dataclass(frozen=True)
class DriftSettings:
    """Parameters of the per-sensor drift detector (EWMA and CUSUM of standardised residuals)."""

    method: str
    baseline_hours: int
    min_baseline_points: int
    min_sigma: float
    smooth_hours: int
    ewma_lambda: float
    ewma_limit: float
    cusum_k: float
    cusum_h: float
    watch_level: float
    confirm_hours: int


@dataclass(frozen=True)
class HealSettings:
    """How the self-healer fits a correction ``raw = gain * expected + offset``."""

    fit_hours: int
    min_pairs: int
    gain_min_pairs: int
    refit_hours: int
    fit_gain: bool
    min_gain: float
    max_gain: float
    trim_mad: float
    min_effect: float
    min_improvement: float
    enabled: bool = True  # False: detect only, publish raw values (ablation)


@dataclass(frozen=True)
class FeedbackSettings:
    """How the maintenance list ranks sensors."""

    min_relative_error: float
    duration_weight_days: float


@dataclass(frozen=True)
class WhatIfSettings:
    """Horizons and history window of the what-if projection."""

    horizons_days: tuple[int, ...]
    history_hours: int
    min_trend_r2: float = 0.0


@dataclass(frozen=True)
class TwinConfig:
    """Settings of the twin's virtual entity."""

    min_training_rows: int
    trust_substitution: bool
    model: ModelParams
    targets: Mapping[str, TargetSpec]
    drift: DriftSettings
    heal: HealSettings
    feedback: FeedbackSettings
    what_if: WhatIfSettings

    def target(self, dataset: str) -> TargetSpec:
        """Return the target settings of one dataset."""
        try:
            return self.targets[dataset]
        except KeyError as exc:
            raise ConfigError(f"no twin targets for dataset {dataset!r}") from exc


DRIFT_TYPES = ("step", "linear", "exponential")


@dataclass(frozen=True)
class BeijingExperiment:
    """How drift is injected into the Beijing data and which period is evaluated."""

    variables: tuple[str, ...]
    evaluation_start: datetime
    min_hours_after_onset: int
    drifted_sensors: int
    magnitude: tuple[float, float]
    ramp_hours: int
    exp_rate: float
    drift_types: tuple[str, ...]
    replay_days: int


@dataclass(frozen=True)
class UciExperiment:
    """Low-cost sensor to reference analyzer pairs and calibration covariates."""

    pairs: Mapping[str, str]
    covariates: tuple[str, ...]


@dataclass(frozen=True)
class BaselineSettings:
    """Parameters of the comparison methods."""

    rolling_window_hours: int
    rolling_every_hours: int
    kalman_q: float
    kalman_r_scale: float


@dataclass(frozen=True)
class SmokeSettings:
    """The reduced experiment set used in CI."""

    seeds: int
    sensitivity_seeds: int
    threshold_scales: tuple[float, ...]
    ewma_lambdas: tuple[float, ...]
    ablation: tuple[str, ...]


@dataclass(frozen=True)
class ExperimentConfig:
    """Everything the reproducible experiments need."""

    seeds: int
    sensitivity_seeds: int
    workers: int
    results_dir: Path
    reference_dir: Path
    tolerance: float
    beijing: BeijingExperiment
    uci: UciExperiment
    baselines: BaselineSettings
    threshold_scales: tuple[float, ...]
    ewma_lambdas: tuple[float, ...]
    what_if_check_days: int
    throughput_hours: int
    smoke: SmokeSettings


@dataclass(frozen=True)
class Config:
    """The complete project configuration."""

    root: Path
    data: DataConfig
    stream: StreamConfig
    twin: TwinConfig
    experiments: ExperimentConfig


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


def _positive_float(raw: Mapping[str, Any], key: str, where: str) -> float:
    """Read a number that must be greater than zero."""
    value = float(_require(raw, key, float, where))
    if not value > 0:
        raise ConfigError(f"{where}.{key} must be positive")
    return value


def _parse_drift(raw: Mapping[str, Any]) -> DriftSettings:
    """Build the drift detector settings and check their ranges."""
    where = "twin.drift"
    method = _require(raw, "method", str, where)
    if method not in DRIFT_METHODS:
        raise ConfigError(f"{where}.method must be one of {DRIFT_METHODS}, got {method!r}")
    ewma_lambda = _positive_float(raw, "ewma_lambda", where)
    if ewma_lambda > 1:
        raise ConfigError(f"{where}.ewma_lambda must be in (0, 1]")
    cusum_k = float(_require(raw, "cusum_k", float, where))
    if cusum_k < 0:
        raise ConfigError(f"{where}.cusum_k must not be negative")
    return DriftSettings(
        method=method,
        baseline_hours=_positive_int(raw, "baseline_hours", where),
        min_baseline_points=_positive_int(raw, "min_baseline_points", where),
        min_sigma=_positive_float(raw, "min_sigma", where),
        smooth_hours=_positive_int(raw, "smooth_hours", where),
        ewma_lambda=ewma_lambda,
        ewma_limit=_positive_float(raw, "ewma_limit", where),
        cusum_k=cusum_k,
        cusum_h=_positive_float(raw, "cusum_h", where),
        watch_level=_positive_float(raw, "watch_level", where),
        confirm_hours=_positive_int(raw, "confirm_hours", where),
    )


def _fraction(raw: Mapping[str, Any], key: str, where: str) -> float:
    """Read a share in [0, 1)."""
    value = float(_require(raw, key, float, where))
    if not 0 <= value < 1:
        raise ConfigError(f"{where}.{key} must be in [0, 1)")
    return value


def _parse_heal(raw: Mapping[str, Any]) -> HealSettings:
    """Build the self-healer settings and check that the gain bounds make sense."""
    where = "twin.heal"
    min_gain = _positive_float(raw, "min_gain", where)
    max_gain = _positive_float(raw, "max_gain", where)
    if not min_gain <= 1 <= max_gain:
        raise ConfigError(f"{where}: min_gain <= 1 <= max_gain must hold")
    fit_hours = _positive_int(raw, "fit_hours", where)
    min_pairs = _positive_int(raw, "min_pairs", where)
    if min_pairs > fit_hours:
        raise ConfigError(f"{where}.min_pairs cannot exceed fit_hours")
    return HealSettings(
        fit_hours=fit_hours,
        min_pairs=min_pairs,
        gain_min_pairs=_positive_int(raw, "gain_min_pairs", where),
        refit_hours=_positive_int(raw, "refit_hours", where),
        fit_gain=_require(raw, "fit_gain", bool, where),
        min_gain=min_gain,
        max_gain=max_gain,
        trim_mad=_positive_float(raw, "trim_mad", where),
        min_effect=_fraction(raw, "min_effect", where),
        min_improvement=_fraction(raw, "min_improvement", where),
        enabled=_require(raw, "enabled", bool, where),
    )


def _parse_feedback(raw: Mapping[str, Any]) -> FeedbackSettings:
    """Build the maintenance-list settings."""
    where = "twin.feedback"
    min_relative_error = float(_require(raw, "min_relative_error", float, where))
    if min_relative_error < 0:
        raise ConfigError(f"{where}.min_relative_error must not be negative")
    return FeedbackSettings(
        min_relative_error=min_relative_error,
        duration_weight_days=_positive_float(raw, "duration_weight_days", where),
    )


def _parse_what_if(raw: Mapping[str, Any]) -> WhatIfSettings:
    """Build the what-if settings; horizons must be positive whole days."""
    where = "twin.what_if"
    horizons = _require(raw, "horizons_days", list, where)
    if not horizons or not all(
        isinstance(h, int) and not isinstance(h, bool) and h > 0 for h in horizons
    ):
        raise ConfigError(f"{where}.horizons_days must be a non-empty list of positive days")
    return WhatIfSettings(
        horizons_days=tuple(sorted(horizons)),
        history_hours=_positive_int(raw, "history_hours", where),
        min_trend_r2=_fraction(raw, "min_trend_r2", where),
    )


def _parse_twin(raw: Mapping[str, Any]) -> TwinConfig:
    """Build the twin section: model parameters, per-dataset targets and drift settings."""
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
            calibration_hours=_positive_int(entry, "calibration_hours", where),
            variables=variables,
            weather=_names(entry, "weather", where),
            reference=_names(entry, "reference", where),
            use_neighbours=_require(entry, "use_neighbours", bool, where),
            use_weather=_require(entry, "use_weather", bool, where),
            use_reference=_require(entry, "use_reference", bool, where),
            use_time=_require(entry, "use_time", bool, where),
        )
    return TwinConfig(
        min_training_rows=_positive_int(raw, "min_training_rows", "twin"),
        trust_substitution=_require(raw, "trust_substitution", bool, "twin"),
        model=model,
        targets=targets,
        drift=_parse_drift(_require(raw, "drift", dict, "twin")),
        heal=_parse_heal(_require(raw, "heal", dict, "twin")),
        feedback=_parse_feedback(_require(raw, "feedback", dict, "twin")),
        what_if=_parse_what_if(_require(raw, "what_if", dict, "twin")),
    )


def _floats(raw: Mapping[str, Any], key: str, where: str) -> tuple[float, ...]:
    """Read a non-empty list of positive numbers."""
    values = _require(raw, key, list, where)
    if not values or not all(
        isinstance(v, int | float) and not isinstance(v, bool) and v > 0 for v in values
    ):
        raise ConfigError(f"{where}.{key} must be a non-empty list of positive numbers")
    return tuple(float(v) for v in values)


def _parse_experiments(raw: Mapping[str, Any], root: Path) -> ExperimentConfig:
    """Build the experiments section and check its ranges."""
    where = "experiments"
    bj = _require(raw, "beijing", dict, where)
    bw = f"{where}.beijing"
    magnitude = _floats(bj, "magnitude", bw)
    if len(magnitude) != 2 or magnitude[0] > magnitude[1]:
        raise ConfigError(f"{bw}.magnitude must be [low, high] with low <= high")
    types = _names(bj, "drift_types", bw)
    if not types or not set(types) <= set(DRIFT_TYPES):
        raise ConfigError(f"{bw}.drift_types must be a non-empty subset of {DRIFT_TYPES}")
    try:
        start = datetime.fromisoformat(_require(bj, "evaluation_start", str, bw))
    except ValueError as exc:
        raise ConfigError(f"{bw}.evaluation_start is not a date and time") from exc
    beijing = BeijingExperiment(
        variables=_names(bj, "variables", bw),
        evaluation_start=start,
        min_hours_after_onset=_positive_int(bj, "min_hours_after_onset", bw),
        drifted_sensors=_positive_int(bj, "drifted_sensors", bw),
        magnitude=(magnitude[0], magnitude[1]),
        ramp_hours=_positive_int(bj, "ramp_hours", bw),
        exp_rate=_positive_float(bj, "exp_rate", bw),
        drift_types=types,
        replay_days=_positive_int(bj, "replay_days", bw),
    )
    uci_raw = _require(raw, "uci", dict, where)
    pairs = _require(uci_raw, "pairs", dict, f"{where}.uci")
    if not pairs or not all(isinstance(k, str) and isinstance(v, str) for k, v in pairs.items()):
        raise ConfigError(f"{where}.uci.pairs must map sensor names to reference names")
    uci = UciExperiment(pairs=dict(pairs), covariates=_names(uci_raw, "covariates", f"{where}.uci"))
    bl = _require(raw, "baselines", dict, where)
    baselines = BaselineSettings(
        rolling_window_hours=_positive_int(bl, "rolling_window_hours", f"{where}.baselines"),
        rolling_every_hours=_positive_int(bl, "rolling_every_hours", f"{where}.baselines"),
        kalman_q=_positive_float(bl, "kalman_q", f"{where}.baselines"),
        kalman_r_scale=_positive_float(bl, "kalman_r_scale", f"{where}.baselines"),
    )
    sens = _require(raw, "sensitivity", dict, where)
    smoke_raw = _require(raw, "smoke", dict, where)
    smoke = SmokeSettings(
        seeds=_positive_int(smoke_raw, "seeds", f"{where}.smoke"),
        sensitivity_seeds=_positive_int(smoke_raw, "sensitivity_seeds", f"{where}.smoke"),
        threshold_scales=_floats(smoke_raw, "threshold_scales", f"{where}.smoke"),
        ewma_lambdas=_floats(smoke_raw, "ewma_lambdas", f"{where}.smoke"),
        ablation=_names(smoke_raw, "ablation", f"{where}.smoke"),
    )
    workers = int(_require(raw, "workers", int, where))
    if workers < 0:
        raise ConfigError(f"{where}.workers must not be negative")
    return ExperimentConfig(
        seeds=_positive_int(raw, "seeds", where),
        sensitivity_seeds=_positive_int(raw, "sensitivity_seeds", where),
        workers=workers,
        results_dir=root / _require(raw, "results_dir", str, where),
        reference_dir=root / _require(raw, "reference_dir", str, where),
        tolerance=_positive_float(raw, "tolerance", where),
        beijing=beijing,
        uci=uci,
        baselines=baselines,
        threshold_scales=_floats(sens, "threshold_scales", f"{where}.sensitivity"),
        ewma_lambdas=_floats(sens, "ewma_lambdas", f"{where}.sensitivity"),
        what_if_check_days=_positive_int(
            _require(raw, "what_if", dict, where), "check_after_days", f"{where}.what_if"
        ),
        throughput_hours=_positive_int(
            _require(raw, "throughput", dict, where), "hours", f"{where}.throughput"
        ),
        smoke=smoke,
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
        experiments=_parse_experiments(_require(raw, "experiments", dict, "config"), root),
    )
