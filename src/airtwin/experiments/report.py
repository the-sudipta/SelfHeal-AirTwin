"""Turn result tables into figures, the README results block and the web-twin replay file.

Figures use one sans-serif font, the Okabe-Ito colour-blind-safe palette, 300 dpi PNG plus
SVG, and no timestamps in the files, so a rerun produces identical figures.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442"]
METHOD_LABELS = {
    "raw": "Raw",
    "one_time": "One-time calibration",
    "rolling": "Rolling recalibration",
    "kalman": "Kalman gain tracking",
    "selfheal": "SelfHeal-AirTwin",
}
START, END = "<!-- results:start -->", "<!-- results:end -->"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "svg.hashsalt": "selfheal-airtwin",
        "svg.fonttype": "none",
    }
)


def _save(fig: Any, figures: Path, name: str) -> list[Path]:
    """Write a figure as PNG (300 dpi) and SVG without creation metadata."""
    figures.mkdir(parents=True, exist_ok=True)
    paths = [figures / f"{name}.png", figures / f"{name}.svg"]
    fig.savefig(paths[0], dpi=300, bbox_inches="tight", metadata={"Software": None})
    fig.savefig(paths[1], bbox_inches="tight", metadata={"Date": None, "Creator": None})
    plt.close(fig)
    return paths


def _grouped_bars(
    ax: Any,
    frame: pd.DataFrame,
    group: str,
    series: str,
    value: str,
    low: str | None = None,
    high: str | None = None,
) -> None:
    """Grouped bar chart with optional confidence-interval whiskers."""
    groups = list(dict.fromkeys(frame[group]))
    names = list(dict.fromkeys(frame[series]))
    width = 0.8 / len(names)
    for i, name in enumerate(names):
        part = frame[frame[series] == name].set_index(group).reindex(groups)
        xs = [g + (i - (len(names) - 1) / 2) * width for g in range(len(groups))]
        err = None
        if low and high:
            err = [
                (part[value] - part[low]).clip(lower=0).fillna(0),
                (part[high] - part[value]).clip(lower=0).fillna(0),
            ]
        ax.bar(
            xs,
            part[value],
            width,
            yerr=err,
            capsize=2,
            color=PALETTE[i % len(PALETTE)],
            label=METHOD_LABELS.get(str(name), str(name)),
        )
    ax.set_xticks(range(len(groups)), [str(g) for g in groups])


def make_figures(results: Path) -> list[Path]:
    """Draw every figure from the tables in ``results`` into ``results/figures``."""
    tables, figures = results / "tables", results / "figures"
    written: list[Path] = []
    uci = pd.read_csv(tables / "uci_methods.csv")
    fig, ax = plt.subplots(figsize=(7, 3))
    norm = uci.assign(rel=uci.rmse / uci.groupby("sensor").rmse.transform("max"))
    _grouped_bars(ax, norm, "sensor", "method", "rel")
    ax.set_ylabel("RMSE vs reference\n(relative to worst method)")
    ax.set_title("UCI Air Quality: error of each method against the reference analyzer")
    ax.legend(fontsize=7, ncol=5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    written += _save(fig, figures, "uci_rmse")

    methods = pd.read_csv(tables / "beijing_methods.csv")
    fig, axes = plt.subplots(1, 3, figsize=(12, 3))
    for ax, scope in zip(axes, ("drifted", "healthy", "all"), strict=True):
        _grouped_bars(
            ax,
            methods[methods.sensors == scope],
            "kind",
            "method",
            "rmse_mean",
            "rmse_ci_low",
            "rmse_ci_high",
        )
        ax.set_title(f"{scope.capitalize()} sensors")
        ax.set_ylabel("RMSE (µg/m³), mean ± 95% CI")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="lower center",
        ncol=5,
        fontsize=7,
        frameon=False,
        bbox_to_anchor=(0.5, -0.08),
    )
    fig.suptitle("Beijing PM2.5 with injected drift: error of published values", y=1.05)
    written += _save(fig, figures, "beijing_rmse")

    runs = pd.read_csv(tables / "beijing_runs.csv")
    main = runs[(runs.variant == "full") & (runs.threshold_scale == 1.0)]
    main = main[main.ewma_lambda == main.ewma_lambda.mode().iloc[0]] if len(main) else main
    kinds = list(dict.fromkeys(main.kind))
    fig, ax = plt.subplots(figsize=(5, 3))
    data = [main[main.kind == k].median_delay_h.dropna() / 24 for k in kinds]
    ax.boxplot(data, tick_labels=kinds)
    ax.set_ylabel("Median detection delay (days)")
    ax.set_title("Detection delay per drift type")
    written += _save(fig, figures, "beijing_delay")

    ablation = pd.read_csv(tables / "ablation.csv")
    fig, axes = plt.subplots(1, 2, figsize=(9, 3))
    for ax, metric, label in zip(
        axes, ("rmse_drifted_selfheal", "f1"), ("RMSE drifted (µg/m³)", "F1"), strict=True
    ):
        ax.bar(
            range(len(ablation)),
            ablation[f"{metric}_mean"],
            color=PALETTE[0],
            yerr=[
                (ablation[f"{metric}_mean"] - ablation[f"{metric}_ci_low"]).fillna(0),
                (ablation[f"{metric}_ci_high"] - ablation[f"{metric}_mean"]).fillna(0),
            ],
            capsize=2,
        )
        ax.set_xticks(range(len(ablation)), ablation.variant, rotation=30, ha="right")
        ax.set_ylabel(label)
    fig.suptitle("Ablation: remove one part at a time")
    written += _save(fig, figures, "ablation")

    sens = pd.read_csv(tables / "sensitivity.csv")
    fig, axes = plt.subplots(1, 2, figsize=(9, 3))
    for ax, parameter in zip(axes, ("threshold_scale", "ewma_lambda"), strict=True):
        part = sens[sens.parameter == parameter].sort_values("value")
        ax.plot(
            part.false_alarms_per_1000h_mean, part.median_delay_h_mean / 24, "o-", color=PALETTE[1]
        )
        for _, row in part.iterrows():
            ax.annotate(
                f"{row.value:g}",
                (row.false_alarms_per_1000h_mean, row.median_delay_h_mean / 24),
                fontsize=7,
            )
        ax.set_xlabel("False alarms per 1,000 sensor-hours")
        ax.set_ylabel("Median delay (days)")
        ax.set_title(parameter.replace("_", " "))
    fig.suptitle("Sensitivity: false alarms against detection delay")
    written += _save(fig, figures, "sensitivity")

    what_if = pd.read_csv(tables / "what_if.csv")
    if not what_if.empty:
        fig, ax = plt.subplots(figsize=(5, 3))
        for i, (kind, part) in enumerate(what_if.groupby("kind", sort=True)):
            ax.plot(
                part.horizon_days,
                part.actual_mean.abs(),
                "o-",
                color=PALETTE[i],
                label=f"{kind}: actual",
            )
            ax.plot(
                part.horizon_days,
                part.projected_mean.abs(),
                "s--",
                color=PALETTE[i],
                label=f"{kind}: projected",
            )
        ax.set_xlabel("Days without recalibration")
        ax.set_ylabel("|relative error|")
        ax.set_title("What-if: projected against actual error growth")
        ax.legend(fontsize=7, frameon=False)
        written += _save(fig, figures, "what_if")
    return written


def _fmt(value: float, digits: int = 2) -> str:
    """Number for a Markdown table; NaN shown as a dash."""
    return "-" if not math.isfinite(value) else f"{value:.{digits}f}"


def results_markdown(results: Path) -> str:
    """The README results block, built only from the result tables."""
    tables = results / "tables"
    uci = pd.read_csv(tables / "uci_methods.csv")
    det = pd.read_csv(tables / "beijing_detection.csv")
    methods = pd.read_csv(tables / "beijing_methods.csv")
    ablation = pd.read_csv(tables / "ablation.csv")
    order = list(METHOD_LABELS)
    lines = [
        "### UCI Air Quality (real drift): RMSE against the reference analyzer",
        "",
        "| Sensor | " + " | ".join(METHOD_LABELS[m] for m in order) + " |",
        "|---|" + "---|" * len(order),
    ]
    for sensor, part in uci.groupby("sensor", sort=True):
        values = part.set_index("method").rmse
        lines.append(
            f"| {sensor} | " + " | ".join(_fmt(values.get(m, math.nan)) for m in order) + " |"
        )
    lines += [
        "",
        "### Beijing PM2.5 (injected drift, years 3-4): detection, mean over runs",
        "",
        "| Drift | Runs | Recall | Precision | False alarms / 1,000 h | Median delay (h) |",
        "|---|---|---|---|---|---|",
    ]
    for _, row in det.iterrows():
        lines.append(
            f"| {row.kind} | {int(row.runs)} | {_fmt(row.recall_mean)} | "
            f"{_fmt(row.precision_mean)} | {_fmt(row.false_alarms_per_1000h_mean)} | "
            f"{_fmt(row.median_delay_h_mean, 0)} |"
        )
    titles = {
        "drifted": "drifting sensors",
        "healthy": "healthy sensors",
        "all": "all sensors",
    }
    for scope, title in titles.items():
        lines += [
            "",
            f"### Beijing PM2.5: RMSE of published values, {title} (µg/m³, mean [95% CI])",
            "",
            "| Drift | " + " | ".join(METHOD_LABELS[m] for m in order) + " |",
            "|---|" + "---|" * len(order),
        ]
        for kind, part in methods[methods.sensors == scope].groupby("kind", sort=True):
            cells = []
            for m in order:
                r = part[part.method == m].iloc[0]
                cells.append(
                    f"{_fmt(r.rmse_mean, 1)} [{_fmt(r.rmse_ci_low, 1)}, {_fmt(r.rmse_ci_high, 1)}]"
                )
            lines.append(f"| {kind} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "### Ablation (mean over runs)",
        "",
        "| Variant | F1 | False alarms / 1,000 h | RMSE drifted | RMSE healthy | RMSE all |",
        "|---|---|---|---|---|---|",
    ]
    for _, row in ablation.iterrows():
        lines.append(
            f"| {row.variant} | {_fmt(row.f1_mean)} | "
            f"{_fmt(row.false_alarms_per_1000h_mean)} | "
            f"{_fmt(row.rmse_drifted_selfheal_mean, 1)} | "
            f"{_fmt(row.rmse_healthy_selfheal_mean, 1)} | "
            f"{_fmt(row.rmse_all_selfheal_mean, 1)} |"
        )
    lines += [
        "",
        "All numbers are produced by `airtwin reproduce`; statistics, figures and the "
        "full tables are listed in [results/README.md](results/README.md).",
    ]
    return "\n".join(lines)


def update_readme(readme: Path, block: str) -> None:
    """Replace the text between the results markers in the README."""
    text = readme.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise ValueError(f"{readme} lacks the {START} / {END} markers")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    readme.write_text(f"{head}{START}\n{block}\n{END}{tail}", encoding="utf-8")


def write_replay(replay: dict[str, Any], paths: Sequence[Path]) -> None:
    """Write the web-twin replay as compact JSON to every given path."""
    text = json.dumps(replay, separators=(",", ":"), sort_keys=True)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
