"""Run every experiment and write the result tables.

* **UCI** (real drift): five estimates of the reference concentration per low-cost sensor —
  ``raw`` (sensor alone, linear map fitted once on the calibration window), ``one_time``
  (sensor plus temperature and humidity, fitted once), ``rolling`` (the same map refitted
  every week on the previous week of reference data), ``kalman`` (gain tracked
  continuously against the twin's expected value, then the one-time map) and ``selfheal``
  (the twin's published value, then the one-time map); scored against the reference.
* **Beijing** (injected drift, years 3-4): per run, drifts of one type are injected into
  random PM2.5 sensors; the twin is scored on detection, and every method on the error of
  its published values against the clean data. Runs repeat over seeds; ablation variants and
  sensitivity settings reuse the same drifts per seed, so comparisons are paired.

Expected-value models depend only on the calibration year, so they are trained once per
model variant and shared by all runs, which execute in parallel worker processes.
"""

from __future__ import annotations

import math
import multiprocessing as mp
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from airtwin.config import Config, TargetSpec
from airtwin.data import beijing_loader, uci_loader
from airtwin.data.datasets import BEIJING_KEY, UCI_KEY
from airtwin.experiments import baselines
from airtwin.experiments.ablation import FULL, apply_sensitivity, apply_variant, model_inputs
from airtwin.experiments.drift_injection import DriftSpec, inject, plan_drifts
from airtwin.experiments.metrics import mae, rmse, score_detection
from airtwin.experiments.stats import mean_ci, wilcoxon_paired
from airtwin.stream.memory_stream import SITE, TIMESTAMP, MemoryStream, wide_to_long
from airtwin.twin.engine import EventKind, TwinEngine
from airtwin.twin.expected_model import ExpectedValueBank, build_specs, column_table, flatten
from airtwin.twin.state import SensorKey

METHODS = ("raw", "one_time", "rolling", "kalman", "selfheal")
BASELINES = METHODS[:-1]
MAX_WORKERS = 6


@dataclass(frozen=True)
class Scenario:
    """One Beijing run: which drifts (kind, seed) and which twin variant."""

    kind: str
    seed: int
    variant: str = FULL
    threshold_scale: float = 1.0
    ewma_lambda: float | None = None
    replay: bool = False

    @property
    def main(self) -> bool:
        """True for the default twin, which also runs the baselines."""
        return self.variant == FULL and self.threshold_scale == 1.0 and self.ewma_lambda is None


@dataclass
class RunResult:
    """Everything one Beijing run produces."""

    scenario: Scenario
    metrics: dict[str, float]
    what_if: list[dict[str, Any]] = field(default_factory=list)
    replay: dict[str, Any] | None = None


@dataclass
class BeijingContext:
    """Data and trained models shared by all Beijing runs (inherited by worker processes)."""

    cfg: Config
    frame: pd.DataFrame  # monitoring period only: pm25 plus weather, long layout
    columns: list[str]
    sites: list[str]
    times: pd.DatetimeIndex
    truth: dict[SensorKey, np.ndarray]
    banks: dict[tuple[bool, bool, bool, bool], ExpectedValueBank]
    target: TargetSpec
    eval_start: int  # index into times


_CONTEXT: BeijingContext | None = None


def _beijing_target(cfg: Config) -> TargetSpec:
    """The Beijing twin restricted to the experiment's variables."""
    return replace(cfg.twin.target(BEIJING_KEY), variables=cfg.experiments.beijing.variables)


def build_beijing_context(cfg: Config, variants: Sequence[str]) -> BeijingContext:
    """Load Beijing, train one model bank per input combination, keep the monitoring period."""
    exp = cfg.experiments.beijing
    archive = cfg.data.raw_dir / cfg.data.dataset(BEIJING_KEY).archive
    full = beijing_loader.load(archive, cfg.data.beijing_missing_token).rename(
        columns={"station": SITE}
    )
    columns = [*exp.variables, *beijing_loader.WEATHER_COLUMNS]
    full = full[[TIMESTAMP, SITE, *columns]]
    sites = sorted(full[SITE].unique())
    target = _beijing_target(cfg)
    start = full[TIMESTAMP].min() + pd.Timedelta(hours=target.calibration_hours)
    calibration = full[full[TIMESTAMP] < start]
    rows = [flatten(t) for t in MemoryStream(calibration, columns)]
    banks: dict[tuple[bool, bool, bool, bool], ExpectedValueBank] = {}
    for variant in variants:
        _, variant_target = apply_variant(cfg.twin, target, variant)
        inputs = model_inputs(variant_target)
        if inputs in banks:
            continue
        bank = ExpectedValueBank(
            build_specs(sites, variant_target),
            cfg.twin.model,
            variant_target.calibration_hours,
            cfg.twin.min_training_rows,
        )
        for row in rows:
            bank.observe(row)
        banks[inputs] = bank
    frame = full[full[TIMESTAMP] >= start].reset_index(drop=True)
    table, _ = column_table(frame, exp.variables)
    times = pd.DatetimeIndex(sorted(frame[TIMESTAMP].unique()))
    keys = [SensorKey(s, v) for s in sites for v in exp.variables]
    truth = {k: table[str(k)] for k in keys}
    eval_start = int(np.searchsorted(times.to_numpy(), np.datetime64(exp.evaluation_start)))
    return BeijingContext(cfg, frame, columns, sites, times, truth, banks, target, eval_start)


def plan_scenario(ctx: BeijingContext, scenario: Scenario) -> list[DriftSpec]:
    """The injected drifts of a scenario: the same for every variant with equal kind and seed."""
    exp = ctx.cfg.experiments.beijing
    kind_index = exp.drift_types.index(scenario.kind)
    rng = np.random.default_rng([scenario.seed, kind_index])
    last_onset = ctx.times[-1].to_pydatetime() - timedelta(hours=exp.min_hours_after_onset)
    window = (exp.evaluation_start, last_onset)
    drifts: list[DriftSpec] = []
    for variable in exp.variables:
        drifts += plan_drifts(
            rng,
            ctx.sites,
            variable,
            scenario.kind,
            exp.drifted_sensors,
            window,
            exp.magnitude,
            exp.ramp_hours,
            exp.exp_rate,
        )
    return drifts


def _replay_frame(
    hour: int, when: datetime, engine: TwinEngine, keys: Sequence[SensorKey]
) -> dict[str, Any]:
    """One hour of the web-twin replay: every sensor's state."""
    assert engine.snapshot is not None
    sensors = []
    for key in keys:
        s = engine.snapshot.sensors[key]
        sensors.append(
            {
                "site": key.site,
                "variable": key.variable,
                "raw": _num(s.raw),
                "expected": _num(s.expected),
                "corrected": _num(s.corrected),
                "score": _num(s.drift_score),
                "status": s.status.value,
                "offset": _num(s.correction.offset),
                "gain": _num(s.correction.gain),
            }
        )
    return {"hour": hour, "time": when.isoformat(), "sensors": sensors}


def _num(value: float) -> float | None:
    """JSON-safe rounded number (NaN becomes null)."""
    return None if not math.isfinite(value) else round(float(value), 4)


def run_beijing(scenario: Scenario) -> RunResult:
    """Run the twin (and, for main runs, the baselines) on one scenario."""
    ctx = _CONTEXT
    assert ctx is not None, "build_beijing_context() must run before run_beijing()"
    cfg, exp = ctx.cfg, ctx.cfg.experiments
    drifts = plan_scenario(ctx, scenario)
    frame = inject(ctx.frame, drifts)
    twin, target = apply_variant(cfg.twin, ctx.target, scenario.variant)
    twin = apply_sensitivity(twin, scenario.threshold_scale, scenario.ewma_lambda)
    bank = ctx.banks[model_inputs(target)]
    engine = TwinEngine(twin, target, ctx.sites, bank=bank)
    keys = engine.keys
    n = len(ctx.times)
    published = {k: np.full(n, math.nan) for k in keys}
    alarm_kind = EventKind.HEAL if twin.heal.enabled else EventKind.DETECT
    alarms: list[tuple[SensorKey, datetime]] = []
    drift_of = {d.key: d for d in drifts}
    first_heal: dict[SensorKey, datetime] = {}
    check_at: dict[SensorKey, datetime] = {}
    what_if: list[dict[str, Any]] = []
    replay_window: tuple[datetime, datetime] | None = None
    if scenario.replay:
        replay_start = drifts[0].onset - timedelta(days=7)
        replay_window = (replay_start, replay_start + timedelta(days=exp.beijing.replay_days))
    frames: list[dict[str, Any]] = []
    events_log: list[dict[str, Any]] = []
    for hour, tick in enumerate(MemoryStream(frame, ctx.columns)):
        result = engine.step(tick)
        now = tick.timestamp
        for key in keys:
            published[key][hour] = result.snapshot.sensors[key].corrected
        for event in result.events:
            if event.kind is alarm_kind and event.key is not None:
                alarms.append((event.key, now))
            if event.kind is EventKind.HEAL and event.key in drift_of:
                spec = drift_of[event.key]
                if now >= spec.onset and event.key not in first_heal:
                    first_heal[event.key] = now
                    check_at[event.key] = now + timedelta(days=exp.what_if_check_days)
            in_replay = replay_window is not None and replay_window[0] <= now < replay_window[1]
            if in_replay and event.kind is not EventKind.WATCH:
                events_log.append(
                    {
                        "time": now.isoformat(),
                        "kind": event.kind.value,
                        "sensor": str(event.key) if event.key else None,
                        "message": event.message,
                    }
                )
        for key, when in list(check_at.items()):
            if now >= when:
                del check_at[key]
                projection = engine.what_if(key)
                spec = drift_of[key]
                for p in projection.projections:
                    what_if.append(
                        {
                            "kind": scenario.kind,
                            "seed": scenario.seed,
                            "sensor": str(key),
                            "horizon_days": p.horizon_days,
                            # no active correction at the check: no projection available
                            "projected": p.relative_error if projection.points_used else math.nan,
                            "actual": spec.relative_error(now + timedelta(days=p.horizon_days)),
                            "current": spec.relative_error(now),
                        }
                    )
        if replay_window is not None and replay_window[0] <= now < replay_window[1]:
            frames.append(_replay_frame(hour, now, engine, keys))
    window = (ctx.times[ctx.eval_start].to_pydatetime(), ctx.times[-1].to_pydatetime())
    score = score_detection(alarms, drifts, window, len(keys))
    metrics: dict[str, float] = {
        "drifts": score.drifts,
        "detected": score.detected,
        "false_alarms": score.false_alarms,
        "precision": score.precision,
        "recall": score.recall,
        "f1": score.f1,
        "false_alarms_per_1000h": score.false_alarms_per_1000h,
        "median_delay_h": score.median_delay_hours,
    }
    estimates = {"selfheal": published}
    if scenario.main:
        estimates.update(_baseline_estimates(ctx, frame, bank, keys))
    healthy = [k for k in keys if k not in drift_of]
    for method, values in estimates.items():
        drifted = [
            rmse(values[d.key][_index(ctx, d.onset) :], ctx.truth[d.key][_index(ctx, d.onset) :])
            for d in drifts
        ]
        healthy_err = [
            rmse(values[k][ctx.eval_start :], ctx.truth[k][ctx.eval_start :]) for k in healthy
        ]
        every = [rmse(values[k][ctx.eval_start :], ctx.truth[k][ctx.eval_start :]) for k in keys]
        metrics[f"rmse_drifted_{method}"] = float(np.nanmean(drifted))
        metrics[f"rmse_healthy_{method}"] = float(np.nanmean(healthy_err))
        metrics[f"rmse_all_{method}"] = float(np.nanmean(every))
    replay = None
    if replay_window is not None:
        replay = {
            "scenario": {"kind": scenario.kind, "seed": scenario.seed},
            "drifts": [
                {
                    "sensor": str(d.key),
                    "kind": d.kind,
                    "onset": d.onset.isoformat(),
                    "magnitude": round(d.magnitude, 4),
                }
                for d in drifts
            ],
            "frames": frames,
            "events": events_log,
            "maintenance": [
                {
                    "rank": i.rank,
                    "sensor": str(i.key),
                    "priority": round(i.priority, 4),
                    "reason": i.reason,
                }
                for i in engine.maintenance_list()
            ],
        }
    return RunResult(scenario, metrics, what_if, replay)


def _index(ctx: BeijingContext, when: datetime) -> int:
    """Position of a time in the monitoring period."""
    return int(np.searchsorted(ctx.times.to_numpy(), np.datetime64(when)))


def _baseline_estimates(
    ctx: BeijingContext, frame: pd.DataFrame, bank: ExpectedValueBank, keys: Sequence[SensorKey]
) -> dict[str, dict[SensorKey, np.ndarray]]:
    """Published values of the four baselines, from the drifted raw data and plain predictions."""
    cfg = ctx.cfg
    bl = cfg.experiments.baselines
    table, length = column_table(frame, ctx.columns)
    base_end = cfg.twin.drift.baseline_hours
    out: dict[str, dict[SensorKey, np.ndarray]] = {m: {} for m in BASELINES}
    for key in keys:
        raw = table[str(key)]
        expected = bank.models[key].predict_table(table, length)
        out["raw"][key] = raw
        calibrated = baselines.one_time(raw, expected, slice(0, base_end))
        out["one_time"][key] = calibrated
        out["rolling"][key] = baselines.rolling(
            raw, expected, ctx.eval_start, bl.rolling_window_hours, bl.rolling_every_hours
        )
        resid = (raw - expected)[:base_end]
        r = bl.kalman_r_scale * float(np.nanvar(resid))
        gains = baselines.kalman_gain(raw, expected, bl.kalman_q, r, start=base_end)
        out["kalman"][key] = raw / gains
    return out


def run_uci(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """UCI experiment: per sensor and method, RMSE and MAE against the reference analyzer."""
    archive = cfg.data.raw_dir / cfg.data.dataset(UCI_KEY).archive
    wide = uci_loader.load(archive, cfg.data.uci_missing_value)
    site = cfg.stream.uci_site
    long = wide_to_long(wide, site)
    columns = [
        *uci_loader.SENSOR_COLUMNS,
        *uci_loader.REFERENCE_COLUMNS,
        *uci_loader.WEATHER_COLUMNS,
    ]
    target = cfg.twin.target(UCI_KEY)
    engine = TwinEngine(cfg.twin, target, [site])
    n = len(wide)
    expected = {k: np.full(n, math.nan) for k in engine.keys}
    published = {k: np.full(n, math.nan) for k in engine.keys}
    for hour, tick in enumerate(MemoryStream(long, columns)):
        snap = engine.step(tick).snapshot
        for key in engine.keys:
            expected[key][hour] = snap.sensors[key].expected
            published[key][hour] = snap.sensors[key].corrected
    exp = cfg.experiments
    cal = target.calibration_hours
    eval_start = cal + cfg.twin.drift.baseline_hours
    covariates = wide[list(exp.uci.covariates)].to_numpy(dtype="float64")
    days = pd.DatetimeIndex(wide.index)[eval_start:].floor("D")
    rows, tests = [], []
    for sensor, reference in exp.uci.pairs.items():
        key = SensorKey(site, sensor)
        raw = wide[sensor].to_numpy(dtype="float64")
        truth = wide[reference].to_numpy(dtype="float64")
        multi = np.column_stack([raw, covariates])
        coef = baselines.fit_linear(multi[:cal], truth[:cal])
        resid = (raw - expected[key])[cal:eval_start]
        r = exp.baselines.kalman_r_scale * float(np.nanvar(resid))
        gains = baselines.kalman_gain(raw, expected[key], exp.baselines.kalman_q, r, start=cal)
        estimates = {
            "raw": baselines.one_time(raw, truth, slice(0, cal)),
            "one_time": baselines.apply_linear(coef, multi),
            "rolling": baselines.rolling(
                multi,
                truth,
                eval_start,
                exp.baselines.rolling_window_hours,
                exp.baselines.rolling_every_hours,
            ),
            "kalman": baselines.apply_linear(coef, np.column_stack([raw / gains, covariates])),
            "selfheal": baselines.apply_linear(coef, np.column_stack([published[key], covariates])),
        }
        daily: dict[str, pd.Series] = {}
        for method, values in estimates.items():
            est, ref = values[eval_start:], truth[eval_start:]
            ok = ~(np.isnan(est) | np.isnan(ref))
            rows.append(
                {
                    "sensor": sensor,
                    "reference": reference,
                    "method": method,
                    "rmse": rmse(est, ref),
                    "mae": mae(est, ref),
                    "hours": int(ok.sum()),
                }
            )
            sq = pd.Series(np.where(ok, (est - ref) ** 2, np.nan), index=days)
            daily[method] = sq.groupby(level=0).mean().pow(0.5)
        for baseline in BASELINES:
            test = wilcoxon_paired(daily["selfheal"].to_numpy(), daily[baseline].to_numpy())
            tests.append(
                {
                    "sensor": sensor,
                    "baseline": baseline,
                    "pairs_days": test.n,
                    "statistic": test.statistic,
                    "p_value": test.p_value,
                    "effect_size": test.effect_size,
                    "median_daily_rmse_difference": test.median_difference,
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(tests)


@dataclass(frozen=True)
class Plan:
    """Which runs to execute."""

    seeds: int
    sensitivity_seeds: int
    threshold_scales: tuple[float, ...]
    ewma_lambdas: tuple[float, ...]
    ablation: tuple[str, ...]


def experiment_plan(cfg: Config, smoke: bool) -> Plan:
    """Full or smoke-test plan from the configuration."""
    exp = cfg.experiments
    if smoke:
        s = exp.smoke
        return Plan(s.seeds, s.sensitivity_seeds, s.threshold_scales, s.ewma_lambdas, s.ablation)
    from airtwin.experiments.ablation import VARIANTS

    return Plan(exp.seeds, exp.sensitivity_seeds, exp.threshold_scales, exp.ewma_lambdas, VARIANTS)


def scenarios_for(cfg: Config, plan: Plan) -> list[Scenario]:
    """Every distinct run: main, ablation, sensitivity (duplicates of main runs are dropped)."""
    kinds = cfg.experiments.beijing.drift_types
    default_lambda = cfg.twin.drift.ewma_lambda
    runs = [
        Scenario(k, s, replay=(k == kinds[0] and s == 0)) for k in kinds for s in range(plan.seeds)
    ]
    cycled = [(kinds[s % len(kinds)], s) for s in range(plan.seeds)]
    for variant in plan.ablation:
        if variant != FULL:
            runs += [Scenario(k, s, variant) for k, s in cycled]
    sens = [(kinds[s % len(kinds)], s) for s in range(plan.sensitivity_seeds)]
    for scale in plan.threshold_scales:
        if scale != 1.0:
            runs += [Scenario(k, s, threshold_scale=scale) for k, s in sens]
    for lam in plan.ewma_lambdas:
        # with both detectors, CUSUM usually decides first, so lambda is also swept with the
        # EWMA alone; the default lambda is written as None so it matches the ablation runs
        value = None if lam == default_lambda else lam
        if value is not None:
            runs += [Scenario(k, s, ewma_lambda=value) for k, s in sens]
        runs += [Scenario(k, s, "ewma_only", ewma_lambda=value) for k, s in sens]
    return list(dict.fromkeys(runs))


def run_all_beijing(
    cfg: Config, plan: Plan, progress: Callable[[str], None] = print
) -> list[RunResult]:
    """Build the shared context, then execute every scenario in parallel worker processes."""
    global _CONTEXT
    _CONTEXT = build_beijing_context(cfg, plan.ablation)
    scenarios = scenarios_for(cfg, plan)
    workers = cfg.experiments.workers or (os.cpu_count() or 1)
    workers = max(1, min(workers, MAX_WORKERS, len(scenarios)))
    progress(f"beijing: {len(scenarios)} runs on {workers} worker processes")
    started = time.perf_counter()
    if workers == 1:
        results = [run_beijing(s) for s in scenarios]
    else:
        with mp.get_context("fork").Pool(workers) as pool:
            results = []
            for i, r in enumerate(pool.imap(run_beijing, scenarios), start=1):
                results.append(r)
                if i % 10 == 0 or i == len(scenarios):
                    progress(f"  {i}/{len(scenarios)} runs, {time.perf_counter() - started:.0f} s")
    _CONTEXT = None
    return results


def summarise_beijing(
    cfg: Config, plan: Plan, results: Sequence[RunResult]
) -> dict[str, pd.DataFrame]:
    """Turn run results into the result and statistics tables."""
    default_lambda = cfg.twin.drift.ewma_lambda
    runs = pd.DataFrame(
        [
            {
                "kind": r.scenario.kind,
                "seed": r.scenario.seed,
                "variant": r.scenario.variant,
                "threshold_scale": r.scenario.threshold_scale,
                "ewma_lambda": r.scenario.ewma_lambda
                if r.scenario.ewma_lambda is not None
                else default_lambda,
                **r.metrics,
            }
            for r in results
        ]
    ).sort_values(["variant", "threshold_scale", "ewma_lambda", "kind", "seed"], ignore_index=True)
    main = runs[
        (runs.variant == FULL)
        & (runs.threshold_scale == 1.0)
        & (runs.ewma_lambda == default_lambda)
    ]
    detection_cols = ["precision", "recall", "f1", "false_alarms_per_1000h", "median_delay_h"]

    def ci_rows(frame: pd.DataFrame, group: list[str], cols: Sequence[str]) -> pd.DataFrame:
        out = []
        for keys, part in frame.groupby(group, sort=True):
            row = dict(zip(group, keys if isinstance(keys, tuple) else (keys,), strict=True))
            for col in cols:
                ci = mean_ci(part[col].tolist())
                row.update(
                    {f"{col}_mean": ci.mean, f"{col}_ci_low": ci.low, f"{col}_ci_high": ci.high}
                )
            row["runs"] = len(part)
            out.append(row)
        return pd.DataFrame(out)

    detection = ci_rows(main, ["kind"], detection_cols)
    method_rows, tests = [], []
    for kind, part in main.groupby("kind", sort=True):
        for method in METHODS:
            for scope in ("drifted", "healthy", "all"):
                ci = mean_ci(part[f"rmse_{scope}_{method}"].tolist())
                method_rows.append(
                    {
                        "kind": kind,
                        "method": method,
                        "sensors": scope,
                        "rmse_mean": ci.mean,
                        "rmse_ci_low": ci.low,
                        "rmse_ci_high": ci.high,
                        "runs": ci.n,
                    }
                )
        for baseline in BASELINES:
            for scope in ("drifted", "healthy", "all"):
                t = wilcoxon_paired(
                    part[f"rmse_{scope}_selfheal"].to_numpy(),
                    part[f"rmse_{scope}_{baseline}"].to_numpy(),
                )
                tests.append(
                    {
                        "kind": kind,
                        "baseline": baseline,
                        "sensors": scope,
                        "pairs": t.n,
                        "statistic": t.statistic,
                        "p_value": t.p_value,
                        "effect_size": t.effect_size,
                        "median_rmse_difference": t.median_difference,
                    }
                )
    cycled = {
        (cfg.experiments.beijing.drift_types[s % len(cfg.experiments.beijing.drift_types)], s)
        for s in range(plan.seeds)
    }
    in_cycle = np.array([(k, s) in cycled for k, s in zip(runs.kind, runs.seed, strict=True)])
    ablation_runs = runs[
        in_cycle & (runs.threshold_scale == 1.0) & (runs.ewma_lambda == default_lambda)
    ]
    ablation_runs = ablation_runs[ablation_runs.variant.isin(plan.ablation)]
    ablation = ci_rows(
        ablation_runs,
        ["variant"],
        [*detection_cols, "rmse_drifted_selfheal", "rmse_healthy_selfheal", "rmse_all_selfheal"],
    )
    full_runs = ablation_runs[ablation_runs.variant == FULL].set_index(["kind", "seed"])
    ablation_tests = []
    for variant in plan.ablation:
        if variant == FULL:
            continue
        other = ablation_runs[ablation_runs.variant == variant].set_index(["kind", "seed"])
        joined = full_runs.join(other, lsuffix="_full", rsuffix="_variant", how="inner")
        for metric, lower_better in (("rmse_drifted_selfheal", True), ("f1", False)):
            a = joined[f"{metric}_full"].to_numpy()
            b = joined[f"{metric}_variant"].to_numpy()
            t = wilcoxon_paired(a, b) if lower_better else wilcoxon_paired(-a, -b)
            ablation_tests.append(
                {
                    "variant": variant,
                    "metric": metric,
                    "pairs": t.n,
                    "statistic": t.statistic,
                    "p_value": t.p_value,
                    "effect_size_full_better": t.effect_size,
                }
            )
    sens_seeds = {
        (cfg.experiments.beijing.drift_types[s % len(cfg.experiments.beijing.drift_types)], s)
        for s in range(plan.sensitivity_seeds)
    }
    in_sens = np.array([(k, s) in sens_seeds for k, s in zip(runs.kind, runs.seed, strict=True)])
    ewma_runs = runs[in_sens & (runs.variant == "ewma_only") & (runs.threshold_scale == 1.0)]
    ewma_runs = ewma_runs[ewma_runs.ewma_lambda.isin(plan.ewma_lambdas)]
    sens_runs = runs[in_sens & (runs.variant == FULL)]
    scale_runs = sens_runs[sens_runs.ewma_lambda == default_lambda]
    scale_runs = scale_runs[scale_runs.threshold_scale.isin(plan.threshold_scales)]
    lambda_runs = sens_runs[sens_runs.threshold_scale == 1.0]
    lambda_runs = lambda_runs[lambda_runs.ewma_lambda.isin(plan.ewma_lambdas)]
    sens_cols = [*detection_cols, "rmse_drifted_selfheal"]
    sensitivity = pd.concat(
        [
            ci_rows(scale_runs, ["threshold_scale"], sens_cols)
            .assign(parameter="threshold_scale")
            .rename(columns={"threshold_scale": "value"}),
            ci_rows(lambda_runs, ["ewma_lambda"], sens_cols)
            .assign(parameter="ewma_lambda")
            .rename(columns={"ewma_lambda": "value"}),
            ci_rows(ewma_runs, ["ewma_lambda"], sens_cols)
            .assign(parameter="ewma_lambda_ewma_only")
            .rename(columns={"ewma_lambda": "value"}),
        ],
        ignore_index=True,
    )
    what_if = pd.DataFrame([w for r in results if r.scenario.main for w in r.what_if])
    if what_if.empty:
        what_if_summary = pd.DataFrame(
            columns=[
                "kind",
                "horizon_days",
                "checks",
                "projections",
                "projected_mean",
                "actual_mean",
                "abs_error_mean",
            ]
        )
    else:
        what_if["abs_error"] = (what_if.projected - what_if.actual).abs()
        what_if_summary = (
            what_if.groupby(["kind", "horizon_days"], sort=True)
            .agg(
                checks=("actual", "size"),
                projections=("projected", "count"),
                projected_mean=("projected", "mean"),
                actual_mean=("actual", "mean"),
                abs_error_mean=("abs_error", "mean"),
            )
            .reset_index()
        )
    return {
        "tables/beijing_runs.csv": runs,
        "tables/beijing_detection.csv": detection,
        "tables/beijing_methods.csv": pd.DataFrame(method_rows),
        "tables/ablation.csv": ablation,
        "tables/sensitivity.csv": sensitivity,
        "tables/what_if.csv": what_if_summary,
        "tables/what_if_checks.csv": what_if,
        "stats/beijing_wilcoxon.csv": pd.DataFrame(tests),
        "stats/ablation_wilcoxon.csv": pd.DataFrame(ablation_tests),
    }


def run_throughput(cfg: Config, kafka: bool) -> pd.DataFrame:
    """Readings per second and milliseconds per hourly cycle of the twin on each backend."""
    global _CONTEXT
    _CONTEXT = build_beijing_context(cfg, [FULL])
    ctx = _CONTEXT
    hours = cfg.experiments.throughput_hours
    start = ctx.times[ctx.eval_start]
    frame = ctx.frame[
        (ctx.frame[TIMESTAMP] >= start) & (ctx.frame[TIMESTAMP] < start + pd.Timedelta(hours=hours))
    ]
    rows = []
    backends = ["memory", "kafka"] if kafka else ["memory"]
    from airtwin.stream import create_stream

    for backend in backends:
        settings = replace(cfg.stream, backend=backend, replay_delay_s=0.0)
        engine = TwinEngine(
            cfg.twin, ctx.target, ctx.sites, bank=ctx.banks[model_inputs(ctx.target)]
        )
        cycles, readings, started = 0, 0, time.perf_counter()
        with create_stream(settings, frame, ctx.columns, name=f"throughput-{backend}") as stream:
            for tick in stream:
                engine.step(tick)
                cycles += 1
                readings += len(tick.readings)
        seconds = time.perf_counter() - started
        rows.append(
            {
                "backend": backend,
                "hours": cycles,
                "sensors": len(engine.keys),
                "readings": readings,
                "seconds": round(seconds, 3),
                "readings_per_s": round(readings / seconds, 1),
                "ms_per_cycle": round(1000 * seconds / max(cycles, 1), 3),
            }
        )
    _CONTEXT = None
    return pd.DataFrame(rows)


def write_tables(base: Path, tables: dict[str, pd.DataFrame]) -> list[Path]:
    """Write tables as CSV with a fixed float format, so reruns produce identical files."""
    written = []
    for name, table in tables.items():
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(path, index=False, float_format="%.10g", lineterminator="\n")
        written.append(path)
    return written
