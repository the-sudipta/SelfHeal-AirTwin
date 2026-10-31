"""Comparison methods, all built from the same inputs the twin has.

* **linear calibration**: least-squares map from inputs to a target, fitted on a fixed
  window and applied for good (``one_time``), or refitted on the previous window at a fixed
  interval (``rolling``, which needs the target during operation);
* **Kalman gain tracking**: continuous estimate of a sensor's multiplicative drift
  ``raw = g_t * expected + noise`` with ``g_t`` a random walk; the corrected reading is
  ``raw / g_t``. It uses the twin's expected value but no detection step.
"""

from __future__ import annotations

import math

import numpy as np


def fit_linear(inputs: np.ndarray, target: np.ndarray, min_rows: int = 2) -> np.ndarray | None:
    """Least-squares coefficients (intercept first) over rows without NaN; None if too few."""
    x = inputs.reshape(len(inputs), -1)
    ok = ~(np.isnan(x).any(axis=1) | np.isnan(target))
    if ok.sum() < max(min_rows, x.shape[1] + 1):
        return None
    design = np.column_stack([np.ones(ok.sum()), x[ok]])
    coef, *_ = np.linalg.lstsq(design, target[ok], rcond=None)
    return np.asarray(coef, dtype="float64")


def apply_linear(coef: np.ndarray | None, inputs: np.ndarray) -> np.ndarray:
    """Apply coefficients from :func:`fit_linear`; NaN where inputs are missing or no fit."""
    x = inputs.reshape(len(inputs), -1)
    if coef is None:
        return np.full(len(x), math.nan)
    return np.asarray(coef[0] + x @ coef[1:], dtype="float64")


def one_time(inputs: np.ndarray, target: np.ndarray, fit_rows: slice) -> np.ndarray:
    """Calibrate once on ``fit_rows`` and apply to every row."""
    return apply_linear(fit_linear(inputs[fit_rows], target[fit_rows]), inputs)


def rolling(
    inputs: np.ndarray, target: np.ndarray, start: int, window: int, every: int
) -> np.ndarray:
    """From row ``start`` on, refit every ``every`` rows on the previous ``window`` rows.

    Rows before ``start`` are NaN. A block whose window has too few rows reuses the last fit.
    """
    out = np.full(len(target), math.nan)
    coef = None
    for block in range(start, len(target), every):
        fitted = fit_linear(
            inputs[max(0, block - window) : block], target[max(0, block - window) : block]
        )
        coef = fitted if fitted is not None else coef
        out[block : block + every] = apply_linear(coef, inputs[block : block + every])
    return out


def kalman_gain(
    raw: np.ndarray, expected: np.ndarray, q: float, r: float, start: int = 0
) -> np.ndarray:
    """Track the multiplicative drift ``g_t`` from row ``start`` on (gain 1 before).

    Scalar Kalman filter: state ``g`` with random-walk variance ``q`` per row, measurement
    ``raw`` with design ``expected`` and noise variance ``r``. Rows with a missing value only
    propagate the uncertainty.
    """
    gains = np.ones(len(raw))
    g, p = 1.0, q
    for t in range(start, len(raw)):
        p += q
        h, z = expected[t], raw[t]
        if math.isfinite(h) and math.isfinite(z) and h > 0:
            s = h * p * h + r
            k = p * h / s
            g += k * (z - h * g)
            p *= 1 - k * h
        gains[t] = g
    return gains
