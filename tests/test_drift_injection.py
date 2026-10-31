from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from airtwin.experiments.drift_injection import (
    EXPONENTIAL,
    LINEAR,
    STEP,
    DriftSpec,
    inject,
    plan_drifts,
)
from airtwin.twin.state import SensorKey

ONSET = datetime(2015, 6, 1)
KEY = SensorKey("A", "pm25")


def spec(kind: str, magnitude: float = 0.4) -> DriftSpec:
    return DriftSpec(KEY, kind, ONSET, magnitude, ramp_hours=100, exp_rate=4.0)


def test_shapes() -> None:
    hours = np.array([-5.0, 0.0, 50.0, 100.0, 200.0])
    assert spec(STEP).shape(hours).tolist() == [0, 1, 1, 1, 1]
    assert spec(LINEAR).shape(hours).tolist() == [0, 0, 0.5, 1, 1]
    exp = spec(EXPONENTIAL).shape(hours)
    assert exp[0] == 0 and exp[1] == 0 and exp[3] == pytest.approx(1) and exp[4] == pytest.approx(1)
    assert 0 < exp[2] < 0.5  # slow start
    with pytest.raises(ValueError, match="unknown drift kind"):
        DriftSpec(KEY, "wave", ONSET, 0.1, 10, 1.0).shape(hours)


def test_factor_and_relative_error() -> None:
    s = spec(LINEAR, magnitude=-0.2)
    assert s.relative_error(ONSET - timedelta(hours=1)) == 0
    assert s.relative_error(ONSET + timedelta(hours=50)) == pytest.approx(-0.1)
    assert s.factor([ONSET + timedelta(hours=500)])[0] == pytest.approx(0.8)


def test_plan_is_reproducible_and_within_bounds() -> None:
    window = (datetime(2015, 3, 1), datetime(2016, 3, 1))
    args = (["A", "B", "C", "D"], "pm25", STEP, 2, window, (0.2, 0.5), 100, 4.0)
    first = plan_drifts(np.random.default_rng(7), *args)
    second = plan_drifts(np.random.default_rng(7), *args)
    assert first == second
    assert len({d.key.site for d in first}) == 2
    for d in first:
        assert window[0] <= d.onset <= window[1]
        assert 0.2 <= abs(d.magnitude) <= 0.5
    with pytest.raises(ValueError, match="more drifting sensors"):
        plan_drifts(np.random.default_rng(0), ["A"], "pm25", STEP, 2, window, (0.2, 0.5), 1, 1.0)


def test_inject_scales_only_the_drifting_sensor() -> None:
    times = pd.to_datetime([ONSET - timedelta(hours=1), ONSET, ONSET + timedelta(hours=10)])
    frame = pd.DataFrame(
        {"timestamp": list(times) * 2, "site": ["A"] * 3 + ["B"] * 3, "pm25": [10.0] * 6}
    )
    out = inject(frame, [spec(STEP, magnitude=0.5)])
    assert out[out.site == "A"].pm25.tolist() == [10.0, 15.0, 15.0]
    assert out[out.site == "B"].pm25.tolist() == [10.0] * 3
    assert frame.pm25.tolist() == [10.0] * 6  # input untouched
