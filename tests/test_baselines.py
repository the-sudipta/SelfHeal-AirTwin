import math

import numpy as np
import pytest

from airtwin.experiments.baselines import (
    apply_linear,
    fit_linear,
    kalman_gain,
    one_time,
    rolling,
)


def test_fit_and_apply_linear() -> None:
    x = np.column_stack([np.arange(10.0), np.arange(10.0) ** 2])
    y = 1.0 + 2.0 * x[:, 0] + 0.5 * x[:, 1]
    y[3] = np.nan
    coef = fit_linear(x, y)
    assert coef is not None
    assert coef == pytest.approx([1.0, 2.0, 0.5])
    assert apply_linear(coef, x)[3] == pytest.approx(1 + 6 + 4.5)
    assert fit_linear(x[:2], y[:2]) is None
    assert np.isnan(apply_linear(None, x)).all()


def test_one_time_ignores_later_drift() -> None:
    x = np.arange(100.0)
    y = 3.0 * x
    drifted = x.copy()
    drifted[50:] *= 1.5
    est = one_time(drifted, y, slice(0, 50))
    assert est[:50] == pytest.approx(y[:50])
    assert est[80] == pytest.approx(3.0 * 1.5 * 80)  # drift passes straight through


def test_rolling_follows_drift_with_one_window_lag() -> None:
    x = np.arange(1.0, 101.0)
    y = 2.0 * x
    sensor = x.copy()
    sensor[50:] *= 1.5
    est = rolling(sensor, y, start=20, window=10, every=10)
    assert np.isnan(est[:20]).all()
    assert est[30] == pytest.approx(y[30])
    assert abs(est[55] - y[55]) > 1  # block 50-59 still uses the pre-drift fit
    assert est[75] == pytest.approx(y[75])


def test_rolling_reuses_last_fit_when_window_is_empty() -> None:
    x = np.arange(1.0, 41.0)
    y = 2.0 * x
    y[20:30] = np.nan
    est = rolling(x, y, start=10, window=10, every=10)
    assert est[35] == pytest.approx(2.0 * x[35])


def test_kalman_tracks_gain() -> None:
    rng = np.random.default_rng(0)
    expected = rng.uniform(20, 100, 3000)
    gain = np.ones(3000)
    gain[1000:] = 1.3
    raw = gain * expected + rng.normal(0, 2, 3000)
    raw[500] = np.nan
    g = kalman_gain(raw, expected, q=1e-4, r=4.0, start=100)
    assert g[:100] == pytest.approx(1.0)
    assert g[900] == pytest.approx(1.0, abs=0.02)
    assert g[2999] == pytest.approx(1.3, abs=0.02)
    assert math.isfinite(g[500])
