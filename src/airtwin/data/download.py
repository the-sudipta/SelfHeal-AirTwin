"""Download the public datasets and verify them against pinned SHA-256 checksums."""

from __future__ import annotations

import hashlib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from airtwin.config import DataConfig, DatasetConfig

CHUNK_BYTES = 1 << 20


class ChecksumError(RuntimeError):
    """Raised when a file is missing from the checksum list or its hash does not match."""


@dataclass(frozen=True)
class DownloadResult:
    """Outcome of fetching one dataset archive."""

    name: str
    path: Path
    sha256: str
    downloaded: bool


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_checksums(path: Path) -> dict[str, str]:
    """Parse a ``sha256sum``-style file into ``{file name: hex digest}``.

    Blank lines and lines starting with ``#`` are ignored. A leading ``*`` before the
    file name (binary mode marker) is accepted.
    """
    checksums: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ChecksumError(f"{path}:{number}: malformed checksum line")
        checksums[parts[1].lstrip("*")] = parts[0].lower()
    return checksums


def verify_file(path: Path, expected: str) -> str:
    """Check a file against its expected digest and return the digest.

    Raises:
        ChecksumError: If the digests differ.
    """
    actual = sha256_file(path)
    if actual != expected:
        raise ChecksumError(f"checksum mismatch for {path.name}: expected {expected}, got {actual}")
    return actual


def _fetch(url: str, dest: Path, timeout_s: float) -> None:
    """Stream ``url`` into ``dest`` through a temporary file so partial downloads never remain."""
    tmp = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response, tmp.open("wb") as out:
            for chunk in iter(lambda: response.read(CHUNK_BYTES), b""):
                out.write(chunk)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def download_dataset(
    dataset: DatasetConfig, raw_dir: Path, checksums: dict[str, str], timeout_s: float
) -> DownloadResult:
    """Make sure one verified archive exists in ``raw_dir``.

    An existing file that matches its checksum is kept. Otherwise the archive is
    downloaded and verified; a mismatching download is deleted before the error is raised.

    Raises:
        ChecksumError: If the archive has no pinned checksum or the download does not match.
    """
    if dataset.archive not in checksums:
        raise ChecksumError(f"no pinned checksum for {dataset.archive}")
    expected = checksums[dataset.archive]
    dest = raw_dir / dataset.archive
    if dest.is_file() and sha256_file(dest) == expected:
        return DownloadResult(dataset.name, dest, expected, downloaded=False)
    raw_dir.mkdir(parents=True, exist_ok=True)
    _fetch(dataset.url, dest, timeout_s)
    try:
        digest = verify_file(dest, expected)
    except ChecksumError:
        dest.unlink(missing_ok=True)
        raise
    return DownloadResult(dataset.name, dest, digest, downloaded=True)


def download_all(cfg: DataConfig) -> list[DownloadResult]:
    """Download and verify every configured dataset, stopping at the first failure."""
    checksums = read_checksums(cfg.checksums_file)
    return [
        download_dataset(dataset, cfg.raw_dir, checksums, cfg.download_timeout_s)
        for dataset in cfg.datasets.values()
    ]


def verify_all(cfg: DataConfig) -> list[DownloadResult]:
    """Verify the archives already in ``raw_dir`` without downloading anything.

    Raises:
        ChecksumError: If an archive is missing or does not match its pinned checksum.
    """
    checksums = read_checksums(cfg.checksums_file)
    results = []
    for dataset in cfg.datasets.values():
        if dataset.archive not in checksums:
            raise ChecksumError(f"no pinned checksum for {dataset.archive}")
        path = cfg.raw_dir / dataset.archive
        if not path.is_file():
            raise ChecksumError(f"missing archive {path}")
        digest = verify_file(path, checksums[dataset.archive])
        results.append(DownloadResult(dataset.name, path, digest, downloaded=False))
    return results
