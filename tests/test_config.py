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
