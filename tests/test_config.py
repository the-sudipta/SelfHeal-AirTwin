from pathlib import Path

import pytest

from airtwin.config import (
    CONFIG_ENV_VAR,
    KAFKA_BOOTSTRAP_ENV_VAR,
    ConfigError,
    default_config_path,
    load_config,
)

REPO = Path(__file__).resolve().parents[1]
DEFAULT = REPO / "configs" / "default.yaml"

MINIMAL = """
data:
  raw_dir: data/raw
  processed_dir: data/processed
  checksums_file: data/checksums.sha256
  download_timeout_s: 30
  datasets:
    demo:
      url: file:///demo.zip
      archive: demo.zip
      processed: demo.csv
  uci_missing_value: -200
  beijing_missing_token: "NA"
stream:
  backend: memory
  replay_delay_s: 0
  uci_site: demo_site
  kafka:
    bootstrap_servers: localhost:9092
    topic_prefix: airtwin
    spark_master: local[1]
    spark_driver_memory: 1g
    spark_jars_dir: jars
    max_offsets_per_trigger: 100
    poll_timeout_s: 1
    idle_timeout_s: 5
twin:
  min_training_rows: 2
  drift:
    method: both
    baseline_hours: 3
    min_baseline_points: 2
    min_sigma: 0.000001
    smooth_hours: 2
    ewma_lambda: 0.1
    ewma_limit: 3
    cusum_k: 0.5
    cusum_h: 5
    watch_level: 0.5
    confirm_hours: 2
  model: {n_estimators: 5, learning_rate: 0.1, num_leaves: 4, min_data_in_leaf: 1, seed: 1}
  targets:
    demo:
      calibration_hours: 3
      variables: [pm25]
      weather: [temperature]
      reference: []
      use_neighbours: true
      use_weather: true
      use_reference: false
      use_time: true
"""


def write_config(tmp_path: Path, text: str) -> Path:
    folder = tmp_path / "configs"
    folder.mkdir()
    path = folder / "default.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_default_config_loads_both_datasets() -> None:
    cfg = load_config(DEFAULT)
    assert cfg.root == REPO
    assert set(cfg.data.datasets) == {"uci_air_quality", "beijing_multisite"}
    assert cfg.data.raw_dir == REPO / "data" / "raw"
    assert cfg.data.uci_missing_value == -200.0
    assert cfg.stream.backend == "memory"
    assert cfg.stream.replay_delay_s == 0.0


def test_stream_section_is_validated(tmp_path: Path) -> None:
    cfg = load_config(write_config(tmp_path, MINIMAL))
    assert cfg.stream.uci_site == "demo_site"
    bad_backend = tmp_path / "a"
    bad_backend.mkdir()
    with pytest.raises(ConfigError, match=r"stream\.backend must be one of"):
        load_config(write_config(bad_backend, MINIMAL.replace("backend: memory", "backend: x")))
    bad_delay = tmp_path / "b"
    bad_delay.mkdir()
    with pytest.raises(ConfigError, match="must not be negative"):
        load_config(
            write_config(bad_delay, MINIMAL.replace("replay_delay_s: 0", "replay_delay_s: -1"))
        )


def test_kafka_section_is_validated_and_env_overrides_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = load_config(write_config(tmp_path, MINIMAL))
    assert cfg.stream.kafka.bootstrap_servers == "localhost:9092"
    assert cfg.stream.kafka.spark_jars_dir == tmp_path.resolve() / "jars"
    monkeypatch.setenv(KAFKA_BOOTSTRAP_ENV_VAR, "broker:29092")
    assert load_config(tmp_path / "configs" / "default.yaml").stream.kafka.bootstrap_servers == (
        "broker:29092"
    )
    bad = tmp_path / "c"
    bad.mkdir()
    with pytest.raises(ConfigError, match=r"poll_timeout_s must be positive"):
        load_config(write_config(bad, MINIMAL.replace("poll_timeout_s: 1", "poll_timeout_s: 0")))


def test_twin_section_is_parsed_and_validated(tmp_path: Path) -> None:
    cfg = load_config(write_config(tmp_path, MINIMAL))
    assert cfg.twin.model.seed == 1
    demo = cfg.twin.target("demo")
    assert demo.calibration_hours == 3
    assert demo.variables == ("pm25",)
    assert demo.use_neighbours is True
    assert demo.use_reference is False
    with pytest.raises(ConfigError, match="no twin targets"):
        cfg.twin.target("other")
    cases = [
        ("calibration_hours: 3", "calibration_hours: 0", "calibration_hours must be at least 1"),
        ("learning_rate: 0.1", "learning_rate: 2", r"learning_rate must be in \(0, 1\]"),
        ("variables: [pm25]", "variables: []", "must not be empty"),
        ("weather: [temperature]", "weather: [1]", "must be a list of names"),
        ("use_time: true", "use_time: 1", "must be bool"),
    ]
    for i, (old, bad, message) in enumerate(cases):
        folder = tmp_path / f"case{i}"
        folder.mkdir()
        with pytest.raises(ConfigError, match=message):
            load_config(write_config(folder, MINIMAL.replace(old, bad)))


def test_drift_section_is_parsed_and_validated(tmp_path: Path) -> None:
    drift = load_config(write_config(tmp_path, MINIMAL)).twin.drift
    assert drift.method == "both"
    assert drift.cusum_h == 5.0
    assert drift.confirm_hours == 2
    cases = [
        ("method: both", "method: other", "method must be one of"),
        ("ewma_lambda: 0.1", "ewma_lambda: 1.5", r"ewma_lambda must be in \(0, 1\]"),
        ("ewma_lambda: 0.1", "ewma_lambda: 0", "ewma_lambda must be positive"),
        ("cusum_k: 0.5", "cusum_k: -1", "cusum_k must not be negative"),
        ("cusum_h: 5", "cusum_h: 0", "cusum_h must be positive"),
        ("confirm_hours: 2", "confirm_hours: 0", "confirm_hours must be at least 1"),
    ]
    for i, (old, bad, message) in enumerate(cases):
        folder = tmp_path / f"drift{i}"
        folder.mkdir()
        with pytest.raises(ConfigError, match=message):
            load_config(write_config(folder, MINIMAL.replace(old, bad)))


def test_default_config_targets_both_datasets() -> None:
    cfg = load_config(DEFAULT)
    assert set(cfg.twin.targets) == {"uci_air_quality", "beijing_multisite"}
    assert "nmhc_ref" not in cfg.twin.target("uci_air_quality").reference
    assert cfg.twin.target("beijing_multisite").calibration_hours == 8760
    assert cfg.twin.drift.smooth_hours == 24


def test_paths_resolve_against_project_root(tmp_path: Path) -> None:
    cfg = load_config(write_config(tmp_path, MINIMAL))
    assert cfg.root == tmp_path.resolve()
    assert cfg.data.checksums_file == tmp_path.resolve() / "data" / "checksums.sha256"
    assert cfg.data.download_timeout_s == 30.0
    assert cfg.data.dataset("demo").archive == "demo.zip"


def test_unknown_dataset_raises(tmp_path: Path) -> None:
    cfg = load_config(write_config(tmp_path, MINIMAL))
    with pytest.raises(ConfigError, match="unknown dataset"):
        cfg.data.dataset("missing")


def test_missing_key_raises(tmp_path: Path) -> None:
    path = write_config(tmp_path, MINIMAL.replace("  raw_dir: data/raw\n", ""))
    with pytest.raises(ConfigError, match=r"missing key data\.raw_dir"):
        load_config(path)


def test_wrong_type_raises(tmp_path: Path) -> None:
    path = write_config(
        tmp_path, MINIMAL.replace("download_timeout_s: 30", "download_timeout_s: x")
    )
    with pytest.raises(ConfigError, match="must be float"):
        load_config(path)


def test_non_mapping_and_missing_file_raise(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not a mapping"):
        load_config(write_config(tmp_path, "- just\n- a list\n"))
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_env_var_selects_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_config(tmp_path, MINIMAL)
    monkeypatch.setenv(CONFIG_ENV_VAR, str(path))
    assert default_config_path() == path.resolve()
    assert "demo" in load_config().data.datasets
