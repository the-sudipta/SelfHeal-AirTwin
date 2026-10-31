"""Command-line entry point: ``airtwin <command>``."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from airtwin import __version__
from airtwin.config import STREAM_BACKENDS, Config, ConfigError, load_config
from airtwin.data import beijing_loader, uci_loader
from airtwin.data.download import ChecksumError, download_all, verify_all
from airtwin.stream import create_stream
from airtwin.stream.interface import StreamError, StreamSource
from airtwin.stream.memory_stream import SITE, wide_to_long

UCI_KEY = "uci_air_quality"
BEIJING_KEY = "beijing_multisite"
Handler = Callable[[Config, argparse.Namespace], int]


def _download(cfg: Config, args: argparse.Namespace) -> int:
    """Download both archives and verify their checksums."""
    for result in download_all(cfg.data):
        state = "downloaded" if result.downloaded else "already present"
        print(f"{result.name}: {state}, sha256 {result.sha256} OK")
    return 0


def _prepare(cfg: Config, args: argparse.Namespace) -> int:
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


def _open_stream(cfg: Config, dataset: str, limit: int | None) -> StreamSource:
    """Load one verified dataset and wrap it in the configured stream backend."""
    data = cfg.data
    archive = data.raw_dir / data.dataset(dataset).archive
    if dataset == UCI_KEY:
        frame = wide_to_long(uci_loader.load(archive, data.uci_missing_value), cfg.stream.uci_site)
        columns = [
            *uci_loader.SENSOR_COLUMNS,
            *uci_loader.REFERENCE_COLUMNS,
            *uci_loader.WEATHER_COLUMNS,
        ]
    else:
        frame = beijing_loader.load(archive, data.beijing_missing_token).rename(
            columns={"station": SITE}
        )
        columns = [*beijing_loader.POLLUTANT_COLUMNS, *beijing_loader.WEATHER_COLUMNS]
    return create_stream(cfg.stream, frame, columns, name=dataset, limit=limit)


def _check(cfg: Config, args: argparse.Namespace) -> int:
    """Confirm the configuration loads and every dataset archive matches its checksum."""
    results = verify_all(cfg.data)
    print(f"ok: config valid, {len(results)} dataset archives verified")
    return 0


def _replay(cfg: Config, args: argparse.Namespace) -> int:
    """Stream one verified dataset tick by tick and report throughput."""
    verify_all(cfg.data)
    with _open_stream(cfg, args.dataset, args.limit) as stream:
        ticks = readings = 0
        started = time.perf_counter()
        for tick in stream:
            ticks += 1
            readings += len(tick.readings)
        elapsed = time.perf_counter() - started
    rate = readings / elapsed if elapsed > 0 else float("inf")
    print(
        f"{args.dataset}: {ticks} ticks, {readings} readings in {elapsed:.2f} s "
        f"({rate:,.0f} readings/s, backend {cfg.stream.backend})"
    )
    return 0


def _add_replay_args(parser: argparse.ArgumentParser) -> None:
    """Options of the replay command."""
    parser.add_argument("--dataset", choices=[UCI_KEY, BEIJING_KEY], default=BEIJING_KEY)
    parser.add_argument("--limit", type=int, default=None, help="stop after this many ticks")


COMMANDS: dict[str, tuple[str, Handler, Callable[[argparse.ArgumentParser], None] | None]] = {
    "download": ("download both datasets and verify their SHA-256 checksums", _download, None),
    "prepare": ("clean both datasets into data/processed (needs download first)", _prepare, None),
    "replay": ("stream one dataset hour by hour and report throughput", _replay, _add_replay_args),
    "check": (
        "verify the configuration and dataset checksums (used as health check)",
        _check,
        None,
    ),
}


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser with one sub-command per entry in :data:`COMMANDS`."""
    parser = argparse.ArgumentParser(prog="airtwin", description="SelfHeal-AirTwin")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=Path, default=None, help="path to a YAML config file")
    parser.add_argument(
        "--backend", choices=STREAM_BACKENDS, default=None, help="override stream.backend"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (help_text, _, add_args) in COMMANDS.items():
        command = sub.add_parser(name, help=help_text)
        if add_args is not None:
            add_args(command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return its exit code (non-zero on any data or config error)."""
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.backend is not None:
            cfg = replace(cfg, stream=replace(cfg.stream, backend=args.backend))
        return COMMANDS[args.command][1](cfg, args)
    except (
        ConfigError,
        ChecksumError,
        StreamError,
        uci_loader.UciFormatError,
        beijing_loader.BeijingFormatError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
