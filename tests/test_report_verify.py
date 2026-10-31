import json
from pathlib import Path

import pandas as pd
import pytest

from airtwin.config import load_config
from airtwin.experiments import report, runner
from airtwin.experiments.verify import compare_table, sha256sums, verify_results

CFG = load_config(Path(__file__).resolve().parents[1] / "configs" / "default.yaml")


def test_full_plan_runs_each_setting_once() -> None:
    plan = runner.experiment_plan(CFG, smoke=False)
    scenarios = runner.scenarios_for(CFG, plan)
    exp = CFG.experiments
    main = [s for s in scenarios if s.main]
    assert len(main) == len(exp.beijing.drift_types) * exp.seeds
    assert len(scenarios) == len(set(scenarios))
    assert sum(s.replay for s in scenarios) == 1
    ablation = [s for s in scenarios if s.variant != "full" and s.ewma_lambda is None]
    assert len(ablation) == (len(plan.ablation) - 1) * exp.seeds
    sens = [s for s in scenarios if s.threshold_scale != 1.0 or s.ewma_lambda is not None]
    extra_scales = len([v for v in plan.threshold_scales if v != 1.0])
    extra_lambdas = len([v for v in plan.ewma_lambdas if v != CFG.twin.drift.ewma_lambda])
    # lambda is swept with both detectors and with the EWMA alone
    assert len(sens) == (extra_scales + 2 * extra_lambdas) * exp.sensitivity_seeds


def test_smoke_plan_is_small() -> None:
    plan = runner.experiment_plan(CFG, smoke=True)
    assert len(runner.scenarios_for(CFG, plan)) <= 6


def _write(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def test_compare_table_tolerance_text_and_shape(tmp_path: Path) -> None:
    ref = _write(tmp_path / "ref.csv", pd.DataFrame({"a": [1.0, float("nan")], "b": ["x", "y"]}))
    same = _write(
        tmp_path / "same.csv", pd.DataFrame({"a": [1.0 + 1e-9, float("nan")], "b": ["x", "y"]})
    )
    assert compare_table(same, ref, 1e-6) == []
    off = _write(tmp_path / "off.csv", pd.DataFrame({"a": [1.1, float("nan")], "b": ["x", "z"]}))
    problems = compare_table(off, ref, 1e-6)
    assert len(problems) == 2 and "row 0 a" in problems[0]
    cols = _write(tmp_path / "cols.csv", pd.DataFrame({"a": [1.0, 2.0]}))
    assert "columns differ" in compare_table(cols, ref, 1e-6)[0]
    rows = _write(tmp_path / "rows.csv", pd.DataFrame({"a": [1.0], "b": ["x"]}))
    assert "rows" in compare_table(rows, ref, 1e-6)[0]
    assert "missing" in compare_table(tmp_path / "none.csv", ref, 1e-6)[0]


def test_verify_results_and_checksums(tmp_path: Path) -> None:
    reference, results = tmp_path / "reference", tmp_path / "results"
    frame = pd.DataFrame({"a": [1.0]})
    _write(reference / "tables" / "t.csv", frame)
    assert verify_results(results, reference, 1e-6)[0].endswith("missing")
    _write(results / "tables" / "t.csv", frame)
    assert verify_results(results, reference, 1e-6) == []
    assert "no reference tables" in verify_results(results, tmp_path / "empty", 1e-6)[0]
    sums = sha256sums(results, [results / "tables" / "t.csv"])
    assert sums.endswith("  tables/t.csv\n") and len(sums.split()[0]) == 64


def _tables(base: Path) -> None:
    t = base / "tables"
    methods = ["raw", "one_time", "rolling", "kalman", "selfheal"]
    _write(
        t / "uci_methods.csv",
        pd.DataFrame(
            {
                "sensor": ["s1_co"] * 5,
                "reference": ["co_ref"] * 5,
                "method": methods,
                "rmse": [1.0, 0.9, 0.7, 0.8, 0.6],
                "mae": [1.0] * 5,
                "hours": [10] * 5,
            }
        ),
    )
    _write(
        t / "beijing_detection.csv",
        pd.DataFrame(
            {
                "kind": ["step"],
                "runs": [2],
                "recall_mean": [1.0],
                "precision_mean": [0.5],
                "false_alarms_per_1000h_mean": [0.6],
                "median_delay_h_mean": [100.0],
            }
        ),
    )
    rows = []
    for scope in ("drifted", "healthy", "all"):
        for m in methods:
            rows.append(
                {
                    "kind": "step",
                    "method": m,
                    "sensors": scope,
                    "rmse_mean": 5.0,
                    "rmse_ci_low": 4.0,
                    "rmse_ci_high": 6.0,
                    "runs": 2,
                }
            )
    _write(t / "beijing_methods.csv", pd.DataFrame(rows))
    _write(
        t / "beijing_runs.csv",
        pd.DataFrame(
            {
                "kind": ["step", "step"],
                "seed": [0, 1],
                "variant": ["full"] * 2,
                "threshold_scale": [1.0] * 2,
                "ewma_lambda": [0.05] * 2,
                "median_delay_h": [90.0, 110.0],
            }
        ),
    )
    ab = {"variant": ["full", "no_weather"]}
    for metric in (
        "f1",
        "false_alarms_per_1000h",
        "rmse_drifted_selfheal",
        "rmse_healthy_selfheal",
        "rmse_all_selfheal",
        "median_delay_h",
    ):
        ab.update(
            {
                f"{metric}_mean": [1.0, 2.0],
                f"{metric}_ci_low": [0.5, 1.5],
                f"{metric}_ci_high": [1.5, 2.5],
            }
        )
    _write(t / "ablation.csv", pd.DataFrame(ab))
    _write(
        t / "sensitivity.csv",
        pd.DataFrame(
            {
                "parameter": ["threshold_scale", "threshold_scale", "ewma_lambda"],
                "value": [1.0, 2.0, 0.05],
                "false_alarms_per_1000h_mean": [0.6, 0.3, 0.6],
                "median_delay_h_mean": [100.0, 150.0, 100.0],
            }
        ),
    )
    _write(
        t / "what_if.csv",
        pd.DataFrame(
            {
                "kind": ["linear", "linear"],
                "horizon_days": [7, 14],
                "checks": [2, 2],
                "projections": [2, 2],
                "projected_mean": [0.2, 0.3],
                "actual_mean": [0.25, 0.3],
                "abs_error_mean": [0.05, 0.0],
            }
        ),
    )


def test_figures_markdown_readme_and_replay(tmp_path: Path) -> None:
    _tables(tmp_path)
    written = report.make_figures(tmp_path)
    assert {p.suffix for p in written} == {".png", ".svg"}
    assert len(written) == 12
    block = report.results_markdown(tmp_path)
    assert "| s1_co | 1.00 | 0.90 | 0.70 | 0.80 | 0.60 |" in block
    assert "| step | 2 | 1.00 | 0.50 | 0.60 | 100 |" in block
    readme = tmp_path / "README.md"
    readme.write_text(f"intro\n{report.START}\nold\n{report.END}\nend\n", encoding="utf-8")
    report.update_readme(readme, "new")
    assert readme.read_text(encoding="utf-8") == f"intro\n{report.START}\nnew\n{report.END}\nend\n"
    readme.write_text("no markers", encoding="utf-8")
    with pytest.raises(ValueError, match="markers"):
        report.update_readme(readme, "new")
    target = tmp_path / "site" / "replay.json"
    report.write_replay({"b": [1], "a": None}, [target])
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": None, "b": [1]}


def test_replay_network_error_uses_a_trailing_window() -> None:
    def frame(raw: float | None, corrected: float) -> dict:
        return {"sensors": [{"raw": raw, "corrected": corrected, "truth": 10.0}]}

    frames = [frame(13.0, 11.0), frame(None, 10.0), frame(14.0, 10.0)]
    runner._replay_network(frames, window=2)
    assert frames[0]["network"] == {"window_hours": 1, "rmse_raw": 3.0, "rmse_published": 1.0}
    assert frames[1]["network"]["rmse_raw"] == 3.0
    assert frames[2]["network"] == {"window_hours": 2, "rmse_raw": 4.0, "rmse_published": 0.0}
