import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import airtwin
from airtwin import cli
from airtwin.cli import main
from airtwin.config import StreamConfig
from airtwin.stream.interface import StreamSource
from test_beijing_loader import A_ROWS, station_csv
from test_beijing_loader import make_archive as make_beijing
from test_uci_loader import ROWS
from test_uci_loader import make_archive as make_uci


def make_project(tmp_path: Path) -> Path:
    remote = tmp_path / "remote"
    remote.mkdir()
    uci = make_uci(remote, ROWS)
    beijing = make_beijing(remote, {"Alpha": station_csv("Alpha", A_ROWS)})
    sums = "".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {name}\n"
        for p, name in [(uci, "uci.zip"), (beijing, "bj.zip")]
    )
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "checksums.sha256").write_text(sums, encoding="utf-8")
    (tmp_path / "configs").mkdir()
    config = tmp_path / "configs" / "default.yaml"
    config.write_text(
        f"""
data:
  raw_dir: data/raw
  processed_dir: data/processed
  checksums_file: data/checksums.sha256
  download_timeout_s: 5
  datasets:
    uci_air_quality: {{url: "{uci.as_uri()}", archive: uci.zip, processed: uci.csv}}
    beijing_multisite: {{url: "{beijing.as_uri()}", archive: bj.zip, processed: bj.csv}}
  uci_missing_value: -200
  beijing_missing_token: "NA"
stream:
  backend: memory
  replay_delay_s: 0
  uci_site: uci_city
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
  trust_substitution: true
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
  heal:
    enabled: true
    fit_hours: 10
    min_pairs: 5
    gain_min_pairs: 8
    refit_hours: 2
    fit_gain: true
    min_gain: 0.5
    max_gain: 2
    trim_mad: 3
    min_effect: 0.1
    min_improvement: 0.3
  feedback:
    min_relative_error: 0.05
    duration_weight_days: 7
  what_if:
    horizons_days: [7, 30]
    history_hours: 48
    min_trend_r2: 0.5
  model:
    n_estimators: 5
    learning_rate: 0.1
    num_leaves: 4
    min_data_in_leaf: 1
    seed: 1
  targets:
    beijing_multisite:
      calibration_hours: 3
      variables: [pm25]
      weather: [temperature]
      reference: []
      use_neighbours: true
      use_weather: true
      use_reference: false
      use_time: true
experiments:
  seeds: 2
  sensitivity_seeds: 1
  workers: 1
  results_dir: results
  reference_dir: results/reference
  tolerance: 0.000001
  beijing:
    variables: [pm25]
    evaluation_start: "2013-03-01 02:00"
    min_hours_after_onset: 1
    drifted_sensors: 1
    magnitude: [0.2, 0.5]
    ramp_hours: 2
    exp_rate: 4
    drift_types: [step, linear]
    replay_days: 1
  uci:
    pairs:
      s1_co: co_ref
    covariates: [temperature]
  baselines:
    rolling_window_hours: 2
    rolling_every_hours: 2
    kalman_q: 0.00001
    kalman_r_scale: 1
  sensitivity:
    threshold_scales: [1.0]
    ewma_lambdas: [0.05]
  what_if:
    check_after_days: 1
  throughput:
    hours: 2
  smoke:
    seeds: 1
    sensitivity_seeds: 1
    threshold_scales: [1.0]
    ewma_lambdas: [0.05]
    ablation: [full]
api:
  host: 127.0.0.1
  port: 8080
  dataset: beijing_multisite
  variables: [pm25]
  fast_forward_hours: 4
  tick_seconds: 0.0
  history_hours: 3
  event_log: 5
  rmse_window_hours: 2
  poll_s: 0.01
  keepalive_s: 1.0
  max_what_if_days: 30
  web_dir: web
  inject:
    kind: step
    magnitude: 0.4
    ramp_hours: 2
    exp_rate: 4.0
""",
        encoding="utf-8",
    )
    return config


def test_download_then_prepare(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = make_project(tmp_path)
    assert main(["--config", str(config), "download"]) == 0
    assert "OK" in capsys.readouterr().out
    assert main(["--config", str(config), "prepare"]) == 0
    out = capsys.readouterr().out
    assert "uci_air_quality: 4 hourly rows" in out
    assert "beijing_multisite: 2 rows, 1 stations" in out
    assert (tmp_path / "data" / "processed" / "uci.csv").is_file()
    assert (tmp_path / "data" / "processed" / "bj.csv").is_file()


def test_replay_streams_both_datasets(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = make_project(tmp_path)
    assert main(["--config", str(config), "download"]) == 0
    capsys.readouterr()
    assert main(["--config", str(config), "replay", "--dataset", "uci_air_quality"]) == 0
    assert "uci_air_quality: 4 ticks, 4 readings" in capsys.readouterr().out
    assert main(["--config", str(config), "replay", "--limit", "1"]) == 0
    assert "beijing_multisite: 1 ticks, 1 readings" in capsys.readouterr().out


def test_backend_flag_overrides_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_project(tmp_path)
    assert main(["--config", str(config), "download"]) == 0
    seen: list[str] = []
    real = cli.create_stream

    def spy(settings: StreamConfig, *args: Any, **kwargs: Any) -> StreamSource:
        seen.append(settings.backend)
        return real(replace(settings, backend="memory"), *args, **kwargs)

    monkeypatch.setattr(cli, "create_stream", spy)
    assert main(["--config", str(config), "--backend", "kafka", "replay", "--limit", "1"]) == 0
    assert seen == ["kafka"]
    assert "backend kafka" in capsys.readouterr().out


def test_check_verifies_config_and_archives(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = make_project(tmp_path)
    assert main(["--config", str(config), "check"]) == 1
    assert main(["--config", str(config), "download"]) == 0
    capsys.readouterr()
    assert main(["--config", str(config), "check"]) == 0
    assert "2 dataset archives verified" in capsys.readouterr().out


def test_prepare_without_download_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = make_project(tmp_path)
    assert main(["--config", str(config), "prepare"]) == 1
    assert "missing archive" in capsys.readouterr().err


def test_bad_config_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(tmp_path / "none.yaml"), "download"]) == 1
    assert "not found" in capsys.readouterr().err


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert airtwin.__version__ in capsys.readouterr().out


def test_twin_command_runs_the_engine(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = make_project(tmp_path)
    assert main(["--config", str(config), "download"]) == 0
    capsys.readouterr()
    assert main(["--config", str(config), "twin", "--dataset", "beijing_multisite"]) == 0
    out = capsys.readouterr().out
    assert "beijing_multisite: 2 hours, 1 sensors" in out
    assert "maintenance list (0 sensors, top 5):" in out


def test_twin_command_prints_events(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = make_project(tmp_path)
    assert main(["--config", str(config), "download"]) == 0
    capsys.readouterr()
    assert (
        main(["--config", str(config), "twin", "--dataset", "beijing_multisite", "--events"]) == 0
    )
    assert "beijing_multisite: 2 hours" in capsys.readouterr().out
