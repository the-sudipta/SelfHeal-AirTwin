import math
from dataclasses import replace

import numpy as np
import pytest

from airtwin.config import DriftSettings
from airtwin.twin.drift_detector import DriftDetector, DriftDetectorBank, RollingMedian
from airtwin.twin.state import SensorKey, SensorStatus

SETTINGS = DriftSettings(
    method="both",
    baseline_hours=200,
    min_baseline_points=50,
    min_sigma=1e-6,
    smooth_hours=6,
    ewma_lambda=0.05,
    ewma_limit=6.0,
    cusum_k=0.5,
    cusum_h=20.0,
    watch_level=0.5,
    confirm_hours=12,
)


def noise(n: int, seed: int = 0, sd: float = 2.0) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0, sd, n)


def warmed(settings: DriftSettings = SETTINGS, seed: int = 0) -> DriftDetector:
    det = DriftDetector(settings)
    for r in noise(settings.baseline_hours, seed) + 5.0:  # residual level 5, spread 2
        assert det.update(float(r)).status is SensorStatus.WARMUP
    assert det.baseline_ready
    return det


def test_rolling_median_ignores_nan_and_needs_a_third_of_the_window() -> None:
    median = RollingMedian(6)
    assert math.isnan(median.push(1.0))
    assert median.push(3.0) == 2.0
    assert median.push(math.nan) == 2.0
    for v in (10.0, 10.0, 10.0, 10.0, 10.0):
        latest = median.push(v)
    assert latest == 10.0


def test_baseline_learns_level_spread_and_observed_smoothed_spreads() -> None:
    det = warmed()
    assert det.center == pytest.approx(5.0, abs=0.5)
    assert det.sigma == pytest.approx(2.0, rel=0.25)
    # a rolling median of 6 hours shrinks the spread of white noise well below 1
    assert 0.1 < det.smooth_sd < 0.9
    # the observed EWMA spread is positive and finite
    assert 0 < det.ewma_sd < 1


def test_baseline_with_too_few_smoothed_points_stays_in_warmup() -> None:
    # 200 raw values pass the point check, but a 200-hour median yields only 134 smoothed ones
    det = DriftDetector(replace(SETTINGS, smooth_hours=200, min_baseline_points=150))
    for r in noise(200):
        det.update(float(r))
    assert not det.baseline_ready


def test_too_few_baseline_points_stays_in_warmup() -> None:
    det = DriftDetector(SETTINGS)
    for i in range(SETTINGS.baseline_hours):
        det.update(1.0 if i < 10 else math.nan)
    assert not det.baseline_ready
    assert det.update(1.0).status is SensorStatus.WARMUP


def test_no_alarm_on_stationary_noise() -> None:
    det = warmed()
    readings = [det.update(float(r)) for r in noise(2000, seed=1) + 5.0]
    assert not any(r.confirmed_now for r in readings)
    assert readings[-1].status in (SensorStatus.HEALTHY, SensorStatus.WATCH)


@pytest.mark.parametrize("method", ["both", "ewma", "cusum"])
def test_step_drift_is_confirmed_with_direction(method: str) -> None:
    det = warmed(replace(SETTINGS, method=method))
    for r in noise(50, seed=2) + 5.0:
        det.update(float(r))
    hours = 0
    for r in noise(500, seed=3) + 5.0 + 6.0:  # +3 sigma step
        hours += 1
        reading = det.update(float(r))
        if reading.confirmed_now:
            break
    assert reading.confirmed_now
    assert reading.status is SensorStatus.DRIFTING
    assert reading.direction == 1
    assert hours < 80
    assert det.update(5.0).status is SensorStatus.DRIFTING  # stays confirmed


def test_slow_negative_drift_is_detected() -> None:
    det = warmed()
    drift = -np.linspace(0, 10, 600)
    readings = [det.update(float(r)) for r in noise(600, seed=4) + 5.0 + drift]
    first = next(i for i, r in enumerate(readings) if r.confirmed_now)
    assert readings[first].direction == -1
    assert 0 < first < 600


def test_watch_before_confirmation_and_reset() -> None:
    det = warmed(replace(SETTINGS, confirm_hours=1000))
    statuses = {det.update(5.0 + 4.0).status for _ in range(200)}
    assert SensorStatus.WATCH in statuses
    assert SensorStatus.DRIFTING not in statuses
    det.reset()
    assert det.ewma == 0.0 and det.cusum_pos == 0.0 and not det.confirmed
    assert det.update(5.0).status is SensorStatus.HEALTHY


def test_missing_hours_eventually_pause_the_statistics() -> None:
    det = warmed()
    for _ in range(6):
        det.update(25.0)
    for _ in range(6):
        det.update(math.nan)  # the window still holds values: statistics keep updating
    before = (det.ewma, det.cusum_pos)
    reading = det.update(math.nan)  # window now mostly empty: statistics pause
    assert (det.ewma, det.cusum_pos) == before
    assert math.isnan(reading.z)
    assert reading.score > 0


def test_bank_updates_every_sensor_and_resets_one() -> None:
    a, b = SensorKey("A", "pm25"), SensorKey("B", "pm25")
    bank = DriftDetectorBank([a, b], replace(SETTINGS, baseline_hours=60, min_baseline_points=10))
    for r in noise(60):
        out = bank.update({a: float(r), b: float(r)})
    assert set(out) == {a, b}
    for _ in range(3):
        out = bank.update({a: 100.0})
    assert out[a].score > out[b].score
    assert out[a].direction == 1
    bank.reset(a)
    assert bank.detectors[a].cusum_pos == 0.0
