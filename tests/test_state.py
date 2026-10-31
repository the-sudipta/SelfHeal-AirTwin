import math
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from airtwin.twin.state import (
    IDENTITY,
    Correction,
    SensorKey,
    SensorState,
    SensorStatus,
    TwinSnapshot,
)

T0 = datetime(2013, 3, 1)


def test_sensor_key_text_round_trip_and_order() -> None:
    key = SensorKey("Dongsi", "pm25")
    assert str(key) == "Dongsi:pm25"
    assert SensorKey.parse("Dongsi:pm25") == key
    assert sorted([SensorKey("B", "a"), SensorKey("A", "z")])[0].site == "A"


@pytest.mark.parametrize("site, variable", [("", "pm25"), ("A", ""), ("A:B", "pm25")])
def test_sensor_key_rejects_ambiguous_names(site: str, variable: str) -> None:
    with pytest.raises(ValueError, match="invalid sensor key"):
        SensorKey(site, variable)


def test_parse_requires_separator() -> None:
    with pytest.raises(ValueError, match="lacks"):
        SensorKey.parse("Dongsi")


def test_correction_applies_offset_and_gain() -> None:
    assert IDENTITY.is_identity
    assert IDENTITY.apply(5.0) == 5.0
    c = Correction(offset=2.0, gain=0.5)
    assert not c.is_identity
    assert c.apply(12.0) == pytest.approx(20.0)
    assert math.isnan(c.apply(math.nan))
    with pytest.raises(ValueError, match="gain must be positive"):
        Correction(gain=0.0)


def test_sensor_state_residual_and_corrected() -> None:
    key = SensorKey("A", "pm25")
    state = SensorState(key)
    assert state.status is SensorStatus.WARMUP
    assert math.isnan(state.residual)
    updated = state.with_reading(raw=30.0, expected=25.0)
    assert updated.residual == 5.0
    assert updated.corrected == 30.0
    healed = SensorState(key, raw=30.0, expected=25.0, correction=Correction(offset=5.0))
    assert healed.corrected == 25.0
    with pytest.raises(FrozenInstanceError):
        updated.raw = 1.0  # type: ignore[misc]


def test_snapshot_is_frozen_sorted_and_queryable() -> None:
    a = SensorState(SensorKey("B", "pm25"), status=SensorStatus.DRIFTING)
    b = SensorState(SensorKey("A", "no2"), status=SensorStatus.HEALTHY)
    c = SensorState(SensorKey("A", "pm25"), status=SensorStatus.HEALTHY)
    snap = TwinSnapshot(T0, {a.key: a, b.key: b, c.key: c})
    assert len(snap) == 3
    assert [str(s.key) for s in snap] == ["A:no2", "A:pm25", "B:pm25"]
    assert snap.sites() == ["A", "B"]
    assert [str(s.key) for s in snap.at_site("A")] == ["A:no2", "A:pm25"]
    assert snap.with_status(SensorStatus.DRIFTING) == [a]
    with pytest.raises(TypeError):
        snap.sensors[a.key] = b  # type: ignore[index]


def test_snapshot_rejects_state_under_wrong_key() -> None:
    a = SensorState(SensorKey("A", "pm25"))
    with pytest.raises(ValueError, match="stored under"):
        TwinSnapshot(T0, {SensorKey("B", "pm25"): a})
