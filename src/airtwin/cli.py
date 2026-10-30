"""Command-line entry point: ``airtwin <command>``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from airtwin import __version__
from airtwin.config import Config, ConfigError, load_config
from airtwin.data import beijing_loader, uci_loader
from airtwin.data.download import ChecksumError, download_all, verify_all

UCI_KEY = "uci_air_quality"
BEIJING_KEY = "beijing_multisite"


def _download(cfg: Config) -> int:
    """Download both archives and verify their checksums."""
    for result in download_all(cfg.data):
        state = "downloaded" if result.downloaded else "already present"
        print(f"{result.name}: {state}, sha256 {result.sha256} OK")
    return 0


def _prepare(cfg: Config) -> int:
    """Verify the archives, clean both datasets and write them to the processed folder."""
    verify_all(cfg.data)
    data = cfg.data
    data.processed_dir.mkdir(parents=True, exist_ok=True)

    uci = data.dataset(UCI_KEY)
    uci_frame = uci_loader.load(data.raw_dir / uci.archive, data.uci_missing_value)
    uci_frame.to_csv(data.processed_dir / uci.processed)
    print(f"{UCI_KEY}: {len(uci_frame)} hourly rows -> {data.processed_dir / uci.processed}")

    beijing = data.dataset(BEIJING_KEY)
    bj_frame = beijing_loader.load(data.raw_dir / beijing.archive, data.beijing_missing_token)
    bj_frame.to_csv(data.processed_dir / beijing.processed, index=False)
    n_sites = len(beijing_loader.stations(bj_frame))
    print(
        f"{BEIJING_KEY}: {len(bj_frame)} rows, {n_sites} stations "
        f"-> {data.processed_dir / beijing.processed}"
    )
    return 0


COMMANDS: dict[str, tuple[str, Callable[[Config], int]]] = {
    "download": ("download both datasets and verify their SHA-256 checksums", _download),
    "prepare": ("clean both datasets into data/processed (needs download first)", _prepare),
}


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser with one sub-command per entry in :data:`COMMANDS`."""
    parser = argparse.ArgumentParser(prog="airtwin", description="SelfHeal-AirTwin")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=Path, default=None, help="path to a YAML config file")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (help_text, _) in COMMANDS.items():
        sub.add_parser(name, help=help_text)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return its exit code (non-zero on any data or config error)."""
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        return COMMANDS[args.command][1](cfg)
    except (
        ConfigError,
        ChecksumError,
        uci_loader.UciFormatError,
        beijing_loader.BeijingFormatError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
