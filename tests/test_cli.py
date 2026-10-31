import hashlib
from pathlib import Path

import pytest

import airtwin
from airtwin.cli import main
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


def test_replay_rejects_unavailable_backend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = make_project(tmp_path)
    config.write_text(config.read_text().replace("backend: memory", "backend: kafka"))
    assert main(["--config", str(config), "download"]) == 0
    assert main(["--config", str(config), "replay"]) == 1
    assert "not available yet" in capsys.readouterr().err


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
