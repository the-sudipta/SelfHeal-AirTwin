import math
from datetime import datetime, timedelta

import numpy as np
import pytest

from airtwin.config import (
    DriftSettings,
    FeedbackSettings,
    HealSettings,
    ModelParams,
    TargetSpec,
    TwinConfig,
    WhatIfSettings,
)
from airtwin.stream.interface import Reading, Tick
from airtwin.twin.engine import EventKind, TwinEngine
from airtwin.twin.state import SensorKey, SensorStatus

SITES = ["A", "B", "C", "D"]
T0 = datetime(2014, 1, 1)
CAL, BASE = 400, 200
TARGET = TargetSpec(
    calibration_hours=CAL,
    variables=("pm25",),
    weather=(),
    reference=(),
    use_neighbours=True,
    use_weather=False,
    use_reference=False,
    use_time=False,
)
TWIN = TwinConfig(
    min_training_rows=100,
    trust_substitution=True,
    model=ModelParams(
        n_estimators=80, learning_rate=0.1, num_leaves=8, min_data_in_leaf=10, seed=1
    ),
    targets={"demo": TARGET},
    drift=DriftSettings(
        method="both",
        baseline_hours=BASE,
        min_baseline_points=100,
        min_sigma=1e-6,
        smooth_hours=6,
        ewma_lambda=0.05,
        ewma_limit=6.0,
        cusum_k=0.5,
        cusum_h=20.0,
        watch_level=0.5,
        confirm_hours=12,
    ),
    heal=HealSettings(
        fit_hours=96,
        min_pairs=18,
        gain_min_pairs=48,
        refit_hours=24,
        fit_gain=True,
        min_gain=0.25,
        max_gain=4.0,
        trim_mad=3.0,
        min_effect=0.1,
        min_improvement=0.3,
    ),
    feedback=FeedbackSettings(min_relative_error=0.05, duration_weight_days=7.0),
    what_if=WhatIfSettings(horizons_days=(7, 30), history_hours=24 * 30),
)
DRIFT_START = CAL + BASE + 300
DRIFT_SITE = "C"


def ticks(hours: int, gain: float = 1.4) -> list[Tick]:
    """A shared regional signal plus small site noise; site C reads 40% high after DRIFT_START."""
    rng = np.random.default_rng(0)
    t = np.arange(hours)
    regional = 60 + 30 * np.sin(t / 37.0) + 15 * np.sin(t / 11.3) + rng.normal(0, 3, hours)
    out = []
    for t in range(hours):
        readings = []
        for i, site in enumerate(SITES):
            value = regional[t] * (1 + 0.1 * i) + rng.normal(0, 1.5)
            if site == DRIFT_SITE and t >= DRIFT_START:
                value *= gain
            readings.append(Reading(site, {"pm25": value}))
        out.append(Tick(T0 + timedelta(hours=t), tuple(readings)))
    return out


@pytest.fixture(scope="module")
def run() -> tuple[TwinEngine, list]:
    engine = TwinEngine(TWIN, TARGET, SITES)
    results = list(engine.run(ticks(DRIFT_START + 400)))
    return engine, results


def test_calibration_and_warmup(run: tuple[TwinEngine, list]) -> None:
    _, results = run
    calibrated = [e for r in results for e in r.events if e.kind is EventKind.CALIBRATED]
    assert len(calibrated) == 1
    assert "4 of 4" in calibrated[0].message
    assert all(s.status is SensorStatus.WARMUP for s in results[0].snapshot)
    assert math.isnan(results[CAL - 1].snapshot.sensors[SensorKey("A", "pm25")].expected)
    assert math.isfinite(results[CAL + 1].snapshot.sensors[SensorKey("A", "pm25")].expected)


def test_drift_is_detected_healed_and_only_on_the_drifting_site(
    run: tuple[TwinEngine, list],
) -> None:
    _, results = run
    events = [e for r in results for e in r.events]
    detect = [e for e in events if e.kind is EventKind.DETECT]
    heal = [e for e in events if e.kind is EventKind.HEAL]
    assert detect and heal
    drifting = SensorKey(DRIFT_SITE, "pm25")
    assert {e.key for e in detect} == {drifting}
    first = detect[0].timestamp
    assert first >= T0 + timedelta(hours=DRIFT_START)
    assert first <= T0 + timedelta(hours=DRIFT_START + 120)
    final = results[-1].snapshot.sensors[drifting]
    assert final.correction.gain == pytest.approx(1.4, abs=0.15)
    assert final.status in (SensorStatus.HEALED, SensorStatus.WATCH, SensorStatus.DRIFTING)
    assert abs(final.corrected - final.expected) < abs(final.raw - final.expected)
    assert any(e.kind is EventKind.REFIT for e in events)


def test_feedback_and_what_if(run: tuple[TwinEngine, list]) -> None:
    engine, _ = run
    drifting = SensorKey(DRIFT_SITE, "pm25")
    items = engine.maintenance_list()
    assert items[0].key == drifting
    assert items[0].relative_error > 0.25
    assert "too high" in items[0].reason
    projection = engine.what_if(drifting)
    assert projection.points_used >= 2
    assert projection.current_relative_error > 0.25
    assert [p.horizon_days for p in projection.projections] == [7, 30]
    custom = engine.what_if(drifting, [3])
    assert [p.horizon_days for p in custom.projections] == [3]


def test_mark_recalibrated_clears_the_sensor(run: tuple[TwinEngine, list]) -> None:
    engine, _ = run
    drifting = SensorKey(DRIFT_SITE, "pm25")
    event = engine.mark_recalibrated(drifting)
    assert event.kind is EventKind.RECALIBRATED
    assert engine.what_if(drifting).points_used == 0
    assert drifting not in {i.key for i in engine.maintenance_list() if i.since}
    with pytest.raises(KeyError):
        engine.mark_recalibrated(SensorKey("Z", "pm25"))


def test_empty_engine_has_no_feedback() -> None:
    engine = TwinEngine(TWIN, TARGET, SITES)
    assert engine.maintenance_list() == []
    assert engine.what_if(SensorKey("A", "pm25")).points_used == 0


def test_without_trust_substitution_healthy_neighbours_get_blamed() -> None:
    from dataclasses import replace

    engine = TwinEngine(replace(TWIN, trust_substitution=False), TARGET, SITES)
    detected = {
        e.key
        for r in engine.run(ticks(DRIFT_START + 400))
        for e in r.events
        if e.kind is EventKind.DETECT
    }
    assert SensorKey(DRIFT_SITE, "pm25") in detected
    assert len(detected) > 1  # the drifting sensor's raw input misleads its neighbours


def test_unconvincing_alarm_is_dismissed_and_no_correction_applied() -> None:
    from airtwin.twin.self_healer import Proposal
    from airtwin.twin.state import Correction

    engine = TwinEngine(TWIN, TARGET, SITES)
    key = SensorKey("A", "pm25")
    engine._onsets[key] = T0
    engine._healers[key].propose = lambda window=None: Proposal(  # type: ignore[method-assign]
        Correction(offset=1.0), relative_error=0.02, improvement=0.05, pairs=60
    )
    events = engine._heal(key, T0, direction=1)
    assert [e.kind for e in events] == [EventKind.DISMISSED]
    assert not engine._healers[key].active
    assert key not in engine._onsets


def test_wrong_direction_correction_is_dismissed() -> None:
    from airtwin.twin.self_healer import Proposal
    from airtwin.twin.state import Correction

    engine = TwinEngine(TWIN, TARGET, SITES)
    key = SensorKey("A", "pm25")
    engine._healers[key].propose = lambda window=None: Proposal(  # type: ignore[method-assign]
        Correction(offset=-20.0), relative_error=-0.3, improvement=0.9, pairs=60
    )
    assert [e.kind for e in engine._heal(key, T0, direction=1)] == [EventKind.DISMISSED]
    assert [e.kind for e in engine._heal(key, T0, direction=-1)] == [EventKind.HEAL]


def test_temporary_shift_is_corrected_then_retired() -> None:
    hours = DRIFT_START + 700
    data = ticks(hours)
    # site C reads 40% high only for 10 days, then recovers by itself
    end = DRIFT_START + 240
    recovered = [
        Tick(
            t.timestamp,
            tuple(
                Reading(r.site, {"pm25": r.values["pm25"] / 1.4})
                if r.site == DRIFT_SITE and i >= end
                else r
                for r in t.readings
            ),
        )
        for i, t in enumerate(data)
    ]
    engine = TwinEngine(TWIN, TARGET, SITES)
    kinds = [
        e.kind
        for r in engine.run(recovered)
        for e in r.events
        if e.key == SensorKey(DRIFT_SITE, "pm25")
    ]
    assert EventKind.HEAL in kinds
    assert EventKind.RECOVERED in kinds
    assert engine.snapshot is not None
    assert engine.snapshot.sensors[SensorKey(DRIFT_SITE, "pm25")].correction.is_identity


def test_detect_only_mode_publishes_raw_values() -> None:
    from dataclasses import replace

    twin = replace(TWIN, heal=replace(TWIN.heal, enabled=False))
    engine = TwinEngine(twin, TARGET, SITES)
    results = list(engine.run(ticks(DRIFT_START + 200)))
    kinds = {e.kind for r in results for e in r.events}
    assert EventKind.DETECT in kinds
    assert EventKind.HEAL not in kinds
    final = results[-1].snapshot.sensors[SensorKey(DRIFT_SITE, "pm25")]
    assert final.correction.is_identity
    alarms = [
        e
        for r in results
        for e in r.events
        if e.kind is EventKind.DETECT and e.key == SensorKey(DRIFT_SITE, "pm25")
    ]
    assert len(alarms) >= 2  # a lasting drift keeps raising alarms


def test_shared_calibrated_bank_skips_calibration() -> None:
    first = TwinEngine(TWIN, TARGET, SITES)
    data = ticks(DRIFT_START + 200)
    list(first.run(data[: CAL + 1]))
    assert first.bank.calibrated
    second = TwinEngine(TWIN, TARGET, SITES, bank=first.bank)
    results = list(second.run(data[CAL + 1 :]))
    assert not any(e.kind is EventKind.CALIBRATED for r in results for e in r.events)
    assert math.isfinite(results[0].snapshot.sensors[SensorKey("A", "pm25")].expected)
    assert any(e.kind is EventKind.HEAL for r in results for e in r.events)
