import math
from datetime import datetime, timedelta

import numpy as np
import pytest

from airtwin.experiments.drift_injection import DriftSpec
from airtwin.experiments.metrics import mae, rmse, score_detection
from airtwin.twin.state import SensorKey

T0 = datetime(2015, 3, 1)
WINDOW = (T0, T0 + timedelta(hours=1000))
A, B, C = SensorKey("A", "pm25"), SensorKey("B", "pm25"), SensorKey("C", "pm25")


def drift(key: SensorKey, onset_hour: int) -> DriftSpec:
    return DriftSpec(key, "step", T0 + timedelta(hours=onset_hour), 0.3, 10, 1.0)


def test_rmse_and_mae_ignore_missing() -> None:
    est = np.array([1.0, 2.0, np.nan, 4.0])
    truth = np.array([1.0, 4.0, 3.0, np.nan])
    assert rmse(est, truth) == pytest.approx(math.sqrt(2))
    assert mae(est, truth) == pytest.approx(1.0)
    assert math.isnan(rmse(np.array([np.nan]), np.array([1.0])))
    assert math.isnan(mae(np.array([np.nan]), np.array([1.0])))


def test_detection_scoring() -> None:
    drifts = [drift(A, 100), drift(B, 500)]
    alarms = [
        (A, T0 + timedelta(hours=50)),  # before onset: false alarm
        (A, T0 + timedelta(hours=130)),  # detects A, delay 30 h
        (A, T0 + timedelta(hours=200)),  # repeat on a detected drift: ignored
        (C, T0 + timedelta(hours=300)),  # never drifts: false alarm
        (C, T0 + timedelta(hours=5000)),  # outside the window: ignored
    ]
    score = score_detection(alarms, drifts, WINDOW, sensors=3)
    assert (score.drifts, score.detected, score.false_alarms) == (2, 1, 2)
    assert score.delays_hours == (30.0,)
    assert score.median_delay_hours == 30.0
    assert score.precision == pytest.approx(1 / 3)
    assert score.recall == pytest.approx(0.5)
    assert score.f1 == pytest.approx(2 * (1 / 3) * 0.5 / (1 / 3 + 0.5))
    assert score.false_alarms_per_1000h == pytest.approx(1000 * 2 / (1000 * 3))


def test_no_alarms_and_no_drifts() -> None:
    score = score_detection([], [drift(A, 10)], WINDOW, sensors=2)
    assert score.recall == 0 and score.f1 == 0.0 and math.isnan(score.precision)
    assert math.isnan(score.median_delay_hours)
    empty = score_detection([], [], WINDOW, sensors=2)
    assert math.isnan(empty.recall)
