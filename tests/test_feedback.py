from datetime import datetime, timedelta

import pytest

from airtwin.config import FeedbackSettings
from airtwin.twin.feedback import rank_sensors
from airtwin.twin.state import Correction, SensorKey, SensorState, SensorStatus, TwinSnapshot

NOW = datetime(2015, 6, 1, 12)
SETTINGS = FeedbackSettings(min_relative_error=0.05, duration_weight_days=7.0)


def state(
    site: str, status: SensorStatus, correction: Correction, score: float = 0.0
) -> SensorState:
    return SensorState(
        SensorKey(site, "pm25"), status=status, correction=correction, drift_score=score
    )


def test_ranking_by_error_and_duration_with_reasons() -> None:
    a = state("A", SensorStatus.HEALED, Correction(offset=10.0))  # +20% at level 50
    b = state("B", SensorStatus.HEALED, Correction(offset=0.0, gain=0.7))  # -30%
    c = state("C", SensorStatus.HEALTHY, Correction(offset=1.0))  # +2%: below threshold
    d = state("D", SensorStatus.HEALTHY, Correction())  # untouched
    snap = TwinSnapshot(NOW, {s.key: s for s in (a, b, c, d)})
    levels = {s.key: 50.0 for s in (a, b, c, d)}
    onsets = {a.key: NOW - timedelta(days=14), b.key: NOW - timedelta(days=1)}
    items = rank_sensors(snap, onsets, levels, SETTINGS)
    assert [i.key.site for i in items] == ["A", "B"]
    assert items[0].rank == 1 and items[1].rank == 2
    assert items[0].priority == pytest.approx(0.2 * (1 + 14 / 7))
    assert items[1].relative_error == pytest.approx(-0.3)
    assert items[0].hours_faulty == pytest.approx(14 * 24)
    assert "reads 20% too high since 2015-05-18 12:00 (14.0 days)" in items[0].reason
    assert "too low" in items[1].reason


def test_confirmed_drift_without_correction_is_listed() -> None:
    e = state("E", SensorStatus.DRIFTING, Correction(), score=2.0)
    snap = TwinSnapshot(NOW, {e.key: e})
    items = rank_sensors(snap, {e.key: NOW}, {}, SETTINGS)
    assert len(items) == 1
    assert items[0].priority == pytest.approx(0.05 * 2.0)
    assert items[0].reason == "drift confirmed, correction not yet estimated"
    assert items[0].since == NOW


def test_ties_are_broken_by_key() -> None:
    x = state("X", SensorStatus.HEALED, Correction(offset=5.0))
    y = state("W", SensorStatus.HEALED, Correction(offset=5.0))
    snap = TwinSnapshot(NOW, {x.key: x, y.key: y})
    items = rank_sensors(snap, {}, {x.key: 50.0, y.key: 50.0}, SETTINGS)
    assert [i.key.site for i in items] == ["W", "X"]
    assert items[0].since is None and "since" not in items[0].reason
