import hashlib
from pathlib import Path

import pytest

from airtwin.config import DataConfig, DatasetConfig
from airtwin.data.download import (
    ChecksumError,
    download_all,
    download_dataset,
    read_checksums,
    sha256_file,
    verify_all,
)

PAYLOAD = b"hourly sensor archive\n" * 1000


def make_source(tmp_path: Path, name: str = "demo.zip") -> tuple[DatasetConfig, str]:
    source = tmp_path / "remote" / name
    source.parent.mkdir(exist_ok=True)
    source.write_bytes(PAYLOAD)
    digest = hashlib.sha256(PAYLOAD).hexdigest()
    return DatasetConfig(name="demo", url=source.as_uri(), archive=name, processed="x.csv"), digest


def make_cfg(tmp_path: Path, dataset: DatasetConfig, digest: str) -> DataConfig:
    sums = tmp_path / "checksums.sha256"
    sums.write_text(f"# pinned\n\n{digest}  {dataset.archive}\n", encoding="utf-8")
    return DataConfig(
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
        checksums_file=sums,
        download_timeout_s=5.0,
        datasets={dataset.name: dataset},
        uci_missing_value=-200.0,
        beijing_missing_token="NA",
    )


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(PAYLOAD)
    assert sha256_file(path) == hashlib.sha256(PAYLOAD).hexdigest()


def test_read_checksums_accepts_binary_marker_and_comments(tmp_path: Path) -> None:
    path = tmp_path / "sums"
    path.write_text("# c\n" + "A" * 64 + " *a.zip\n" + "b" * 64 + "  b.zip\n", encoding="utf-8")
    assert read_checksums(path) == {"a.zip": "a" * 64, "b.zip": "b" * 64}


def test_read_checksums_rejects_malformed_line(tmp_path: Path) -> None:
    path = tmp_path / "sums"
    path.write_text("not-a-hash a.zip\n", encoding="utf-8")
    with pytest.raises(ChecksumError, match="malformed"):
        read_checksums(path)


def test_download_verifies_and_then_reuses(tmp_path: Path) -> None:
    dataset, digest = make_source(tmp_path)
    cfg = make_cfg(tmp_path, dataset, digest)
    first = download_all(cfg)
    assert first[0].downloaded
    assert first[0].path.read_bytes() == PAYLOAD
    second = download_all(cfg)
    assert not second[0].downloaded
    assert verify_all(cfg)[0].sha256 == digest


def test_mismatch_stops_and_leaves_no_file(tmp_path: Path) -> None:
    dataset, _ = make_source(tmp_path)
    wrong = "0" * 64
    with pytest.raises(ChecksumError, match="mismatch"):
        download_dataset(dataset, tmp_path / "raw", {dataset.archive: wrong}, 5.0)
    assert not (tmp_path / "raw" / dataset.archive).exists()
    assert not (tmp_path / "raw" / f"{dataset.archive}.part").exists()


def test_corrupted_local_copy_is_replaced(tmp_path: Path) -> None:
    dataset, digest = make_source(tmp_path)
    cfg = make_cfg(tmp_path, dataset, digest)
    cfg.raw_dir.mkdir()
    (cfg.raw_dir / dataset.archive).write_bytes(b"tampered")
    assert download_all(cfg)[0].downloaded
    assert sha256_file(cfg.raw_dir / dataset.archive) == digest


def test_unpinned_archive_is_refused(tmp_path: Path) -> None:
    dataset, _ = make_source(tmp_path)
    with pytest.raises(ChecksumError, match="no pinned checksum"):
        download_dataset(dataset, tmp_path / "raw", {}, 5.0)


def test_verify_all_reports_missing_and_tampered(tmp_path: Path) -> None:
    dataset, digest = make_source(tmp_path)
    cfg = make_cfg(tmp_path, dataset, digest)
    cfg.checksums_file.write_text("", encoding="utf-8")
    with pytest.raises(ChecksumError, match="no pinned checksum"):
        verify_all(cfg)
    cfg = make_cfg(tmp_path, dataset, digest)
    with pytest.raises(ChecksumError, match="missing archive"):
        verify_all(cfg)
    cfg.raw_dir.mkdir()
    (cfg.raw_dir / dataset.archive).write_bytes(b"tampered")
    with pytest.raises(ChecksumError, match="mismatch"):
        verify_all(cfg)
