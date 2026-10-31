"""Command-line entry point: ``airtwin <command>``."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

import pandas as pd

from airtwin import __version__
from airtwin.config import STREAM_BACKENDS, Config, ConfigError, load_config
from airtwin.data import beijing_loader, uci_loader
from airtwin.data.download import ChecksumError, download_all, verify_all
from airtwin.experiments import report, runner
from airtwin.experiments.verify import MAX_REPORTED, sha256sums, verify_results
from airtwin.stream import create_stream
from airtwin.stream.interface import StreamError, StreamSource
from airtwin.stream.memory_stream import SITE, wide_to_long
from airtwin.twin.engine import EventKind, TwinEngine

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


def _load_frame(cfg: Config, dataset: str) -> tuple[pd.DataFrame, list[str]]:
    """Load one verified dataset as a long table and name its numeric columns."""
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
    return frame, columns


def _open_stream(cfg: Config, dataset: str, limit: int | None) -> StreamSource:
    """Load one verified dataset and wrap it in the configured stream backend."""
    frame, columns = _load_frame(cfg, dataset)
    return create_stream(cfg.stream, frame, columns, name=dataset, limit=limit)


def _twin(cfg: Config, args: argparse.Namespace) -> int:
    """Run the full twin over one dataset and report events, maintenance list and what-if."""
    verify_all(cfg.data)
    frame, columns = _load_frame(cfg, args.dataset)
    engine = TwinEngine.for_dataset(cfg, args.dataset, frame[SITE].unique())
    counts: Counter[str] = Counter()
    hours = 0
    started = time.perf_counter()
    stream = create_stream(cfg.stream, frame, columns, name=args.dataset, limit=args.limit)
    with stream:
        for result in engine.run(stream):
            hours += 1
            for event in result.events:
                counts[event.kind.value] += 1
                if args.events and event.kind is not EventKind.WATCH:
                    print(
                        f"{event.timestamp:%Y-%m-%d %H:%M} {event.kind.value:12s} "
                        f"{event.key or ''!s:24} {event.message}"
                    )
    elapsed = time.perf_counter() - started
    summary = ", ".join(f"{kind} {counts[kind]}" for kind in sorted(counts)) or "no events"
    print(f"{args.dataset}: {hours} hours, {len(engine.keys)} sensors, {elapsed:.1f} s; {summary}")
    items = engine.maintenance_list()
    print(f"maintenance list ({len(items)} sensors, top {args.top}):")
    for item in items[: args.top]:
        print(f"  {item.rank:2d}. {item.key}  priority {item.priority:.3f}  {item.reason}")
    if items:
        what_if = engine.what_if(items[0].key)
        steps = ", ".join(
            f"{p.horizon_days} d: {p.relative_error:+.1%}" for p in what_if.projections
        )
        print(f"what-if for {items[0].key} without recalibration: {steps} ({what_if.basis})")
    return 0


def _add_twin_args(parser: argparse.ArgumentParser) -> None:
    """Options of the twin command."""
    _add_replay_args(parser)
    parser.add_argument("--top", type=int, default=5, help="maintenance list entries to show")
    parser.add_argument("--events", action="store_true", help="print every non-watch event")


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


def _result_dirs(cfg: Config, smoke: bool) -> tuple[Path, Path]:
    """Output and reference folders of the full or smoke experiment set."""
    exp = cfg.experiments
    mode = "smoke" if smoke else "full"
    output = exp.results_dir / "smoke" if smoke else exp.results_dir
    return output, exp.reference_dir / mode


def _verify(cfg: Config, args: argparse.Namespace) -> int:
    """Check dataset checksums and compare regenerated tables with the reference, value by value."""
    verify_all(cfg.data)
    output, reference = _result_dirs(cfg, args.smoke)
    problems = verify_results(output, reference, cfg.experiments.tolerance)
    if problems:
        for line in problems[:MAX_REPORTED]:
            print(f"DIFF {line}")
        extra = len(problems) - MAX_REPORTED
        print(f"FAIL: {len(problems)} differences" + (f" ({extra} not shown)" if extra > 0 else ""))
        return 1
    tables = len(list(reference.rglob("*.csv")))
    print(
        f"PASS: datasets verified; {tables} result tables match the reference "
        f"(tolerance {cfg.experiments.tolerance:g})"
    )
    return 0


def _report(cfg: Config, args: argparse.Namespace) -> int:
    """Draw figures, update the README results block and export the web-twin replay."""
    output, _ = _result_dirs(cfg, args.smoke)
    figures = report.make_figures(output)
    print(f"report: {len(figures)} figure files in {output / 'figures'}")
    replay_file = output / "replay.json"
    if not args.smoke:
        report.update_readme(cfg.root / "README.md", report.results_markdown(output))
        print("report: README results block updated")
        if replay_file.is_file():
            report.write_replay(
                json.loads(replay_file.read_text(encoding="utf-8")),
                [cfg.root / "site" / "data" / "replay.json"],
            )
            print("report: site/data/replay.json written")
    return 0


def _reproduce(cfg: Config, args: argparse.Namespace) -> int:
    """Run every experiment, write tables, figures and checksums, then verify."""
    verify_all(cfg.data)
    output, reference = _result_dirs(cfg, args.smoke)
    started = time.perf_counter()
    uci, uci_tests = runner.run_uci(cfg)
    tables = {"tables/uci_methods.csv": uci, "stats/uci_wilcoxon.csv": uci_tests}
    print(f"uci: done in {time.perf_counter() - started:.0f} s")
    plan = runner.experiment_plan(cfg, args.smoke)
    results = runner.run_all_beijing(cfg, plan)
    tables.update(runner.summarise_beijing(cfg, plan, results))
    written = runner.write_tables(output, tables)
    replay = next((r.replay for r in results if r.replay), None)
    if replay is not None:
        report.write_replay(replay, [output / "replay.json"])
    benchmark = runner.run_throughput(cfg, kafka=args.kafka)
    runner.write_tables(output, {"benchmark/throughput.csv": benchmark})
    print(benchmark.to_string(index=False))
    _report(cfg, args)
    if not args.smoke:
        files = [
            p
            for p in output.rglob("*")
            if p.is_file()
            and p.name != "SHA256SUMS"
            and "reference" not in p.relative_to(output).parts
            and "smoke" not in p.relative_to(output).parts
        ]
        (output / "SHA256SUMS").write_text(sha256sums(output, files), encoding="utf-8")
    print(f"reproduce: {len(written)} tables in {time.perf_counter() - started:.0f} s")
    if args.update_reference:
        runner.write_tables(
            reference,
            {str(p.relative_to(output)).replace("\\", "/"): pd.read_csv(p) for p in written},
        )
        print(f"reference tables written to {reference}")
        return 0
    return _verify(cfg, args)


def _add_experiment_args(parser: argparse.ArgumentParser) -> None:
    """Options shared by reproduce, verify and report."""
    parser.add_argument("--smoke", action="store_true", help="the small seeded CI slice")


def _add_reproduce_args(parser: argparse.ArgumentParser) -> None:
    """Options of the reproduce command."""
    _add_experiment_args(parser)
    parser.add_argument(
        "--kafka", action="store_true", help="also time the Kafka + Spark backend (needs a broker)"
    )
    parser.add_argument(
        "--update-reference",
        action="store_true",
        help="store the regenerated tables as the new reference",
    )


def _add_replay_args(parser: argparse.ArgumentParser) -> None:
    """Options of the replay command."""
    parser.add_argument("--dataset", choices=[UCI_KEY, BEIJING_KEY], default=BEIJING_KEY)
    parser.add_argument("--limit", type=int, default=None, help="stop after this many ticks")


COMMANDS: dict[str, tuple[str, Handler, Callable[[argparse.ArgumentParser], None] | None]] = {
    "download": ("download both datasets and verify their SHA-256 checksums", _download, None),
    "prepare": ("clean both datasets into data/processed (needs download first)", _prepare, None),
    "replay": ("stream one dataset hour by hour and report throughput", _replay, _add_replay_args),
    "twin": (
        "run the digital twin over one dataset: detect, heal, rank maintenance",
        _twin,
        _add_twin_args,
    ),
    "reproduce": (
        "rerun every experiment, write tables, figures and checksums, then verify",
        _reproduce,
        _add_reproduce_args,
    ),
    "verify": (
        "compare regenerated tables with the reference and check dataset checksums",
        _verify,
        _add_experiment_args,
    ),
    "report": (
        "draw figures, update the README results and export the web-twin replay",
        _report,
        _add_experiment_args,
    ),
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
