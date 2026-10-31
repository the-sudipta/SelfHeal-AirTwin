"""Drift detection: smooth each sensor's residual over time and raise an alarm on lasting change.

After calibration, each sensor first spends a baseline window in which the detector learns
the normal level (median) and spread (scaled MAD) of its residual ``raw - expected``.
Afterwards each hour:

1. The residual is smoothed with a rolling median over ``smooth_hours``. Drift lasts days,
   pollution episodes last hours, so the median suppresses episodes but keeps drift.
2. The smoothed residual is standardised with the baseline level, spread and the spread of
   the smoothed baseline series itself.
3. Two classic change detectors run on it: an EWMA ``s_t = lambda * z_t + (1 - lambda) * s_{t-1}``
   (sensitive to slow drift) and a two-sided CUSUM ``C+ = max(0, C+ + z - k)``,
   ``C- = max(0, C- - z - k)`` (sensitive to small persistent shifts).

Air-quality residuals are strongly autocorrelated, so the EWMA limit is not taken from the
textbook formula for independent noise: the EWMA is replayed over the baseline and its
observed standard deviation is used. The drift score is the larger ratio of statistic to
threshold, so 1.0 means "at the alarm line". Drift is confirmed after ``confirm_hours``
consecutive alarm hours and stays confirmed until :meth:`DriftDetector.reset`.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np

from airtwin.config import DriftSettings
from airtwin.twin.state import SensorKey, SensorStatus

MAD_TO_SIGMA = 1.4826  # scales the median absolute deviation to a normal standard deviation


@dataclass(frozen=True)
class DriftReading:
    """The detector's verdict for one sensor after one hour."""

    status: SensorStatus
    score: float = 0.0
    direction: int = 0  # +1 reads too high, -1 too low, 0 undecided
    alarm: bool = False  # the score is at or above 1 this hour
    confirmed_now: bool = False  # drift was confirmed in exactly this hour
    z: float = math.nan  # standardised smoothed residual of this hour


class RollingMedian:
    """Median of the last ``window`` values, ignoring NaN; NaN until enough values exist."""

    def __init__(self, window: int) -> None:
        """Keep at most ``window`` values; require a third of them before answering."""
        self._values: deque[float] = deque(maxlen=window)
        self._min_count = max(1, window // 3)

    def push(self, value: float) -> float:
        """Add one value and return the current median."""
        self._values.append(value)
        present = [v for v in self._values if not math.isnan(v)]
        if len(present) < self._min_count:
            return math.nan
        return float(np.median(present))


class DriftDetector:
    """Smoothed EWMA and CUSUM drift detector for one sensor."""

    def __init__(self, settings: DriftSettings) -> None:
        """Start in the baseline phase."""
        self._s = settings
        self._baseline: list[float] = []
        self._hours_seen = 0
        self.center = math.nan  # baseline median of the raw residual
        self.sigma = math.nan  # baseline robust spread of the raw residual
        self.smooth_sd = math.nan  # spread of the standardised, smoothed baseline residual
        self.ewma_sd = math.nan  # observed spread of the EWMA over the baseline
        self._median = RollingMedian(settings.smooth_hours)
        self.reset()

    @property
    def baseline_ready(self) -> bool:
        """True once the normal residual level and spreads are known."""
        return not math.isnan(self.ewma_sd)

    def reset(self, forget_window: bool = False) -> None:
        """Clear the statistics and the confirmed state, keeping the learned baseline.

        With ``forget_window`` the rolling-median window is emptied too, so residuals computed
        before the reset (e.g. from an input now known to be faulty) no longer count.
        """
        if forget_window:
            self._median = RollingMedian(self._s.smooth_hours)
        self.ewma = 0.0
        self.cusum_pos = 0.0
        self.cusum_neg = 0.0
        self._streak = 0
        self.confirmed = False

    def _finish_baseline(self) -> None:
        """Learn level, spread and the spreads of the smoothed series and its EWMA."""
        values = np.asarray(self._baseline, dtype="float64")
        self._baseline = []
        present = values[~np.isnan(values)]
        if len(present) < self._s.min_baseline_points:
            return
        center = float(np.median(present))
        sigma = max(MAD_TO_SIGMA * float(np.median(np.abs(present - center))), self._s.min_sigma)
        median = RollingMedian(self._s.smooth_hours)
        smoothed = np.array([median.push(v) for v in values])
        z = (smoothed[~np.isnan(smoothed)] - center) / sigma
        if len(z) < self._s.min_baseline_points:
            return
        smooth_sd = max(float(np.std(z)), self._s.min_sigma)
        ewma, trace = 0.0, []
        for v in z / smooth_sd:
            ewma = self._s.ewma_lambda * v + (1 - self._s.ewma_lambda) * ewma
            trace.append(ewma)
        settled = trace[self._s.smooth_hours :] or trace
        self.center, self.sigma, self.smooth_sd = center, sigma, smooth_sd
        self.ewma_sd = max(float(np.std(settled)), self._s.min_sigma)
        self._median = median  # continue the rolling window seamlessly into monitoring

    def _score(self) -> tuple[float, int]:
        """Combined score and its direction from the statistics of the chosen method."""
        candidates: list[tuple[float, int]] = []
        if self._s.method in ("both", "ewma"):
            limit = self._s.ewma_limit * self.ewma_sd
            candidates.append((abs(self.ewma) / limit, 1 if self.ewma > 0 else -1))
        if self._s.method in ("both", "cusum"):
            candidates.append((self.cusum_pos / self._s.cusum_h, 1))
            candidates.append((self.cusum_neg / self._s.cusum_h, -1))
        score, direction = max(candidates)
        return score, direction if score > 0 else 0

    def update(self, residual: float) -> DriftReading:
        """Process one hour's residual; hours without a usable value keep the statistics."""
        if not self.baseline_ready:
            self._hours_seen += 1
            self._baseline.append(residual)
            if self._hours_seen >= self._s.baseline_hours:
                self._finish_baseline()
            return DriftReading(SensorStatus.WARMUP)
        smoothed = self._median.push(residual)
        if math.isnan(smoothed):
            score, direction = self._score()
            return DriftReading(self._status(score), score, direction, score >= 1)
        z = (smoothed - self.center) / self.sigma / self.smooth_sd
        lam = self._s.ewma_lambda
        self.ewma = lam * z + (1 - lam) * self.ewma
        self.cusum_pos = max(0.0, self.cusum_pos + z - self._s.cusum_k)
        self.cusum_neg = max(0.0, self.cusum_neg - z - self._s.cusum_k)
        score, direction = self._score()
        alarm = score >= 1
        self._streak = self._streak + 1 if alarm else 0
        confirmed_now = not self.confirmed and self._streak >= self._s.confirm_hours
        self.confirmed = self.confirmed or confirmed_now
        return DriftReading(self._status(score), score, direction, alarm, confirmed_now, z)

    def _status(self, score: float) -> SensorStatus:
        """Map the current score and confirmation to a status."""
        if self.confirmed:
            return SensorStatus.DRIFTING
        if score >= self._s.watch_level:
            return SensorStatus.WATCH
        return SensorStatus.HEALTHY


class DriftDetectorBank:
    """One detector per sensor."""

    def __init__(self, keys: Iterable[SensorKey], settings: DriftSettings) -> None:
        """Create a detector for every key."""
        self.detectors = {key: DriftDetector(settings) for key in keys}

    def update(self, residuals: Mapping[SensorKey, float]) -> dict[SensorKey, DriftReading]:
        """Feed one hour of residuals; sensors absent from ``residuals`` count as missing."""
        return {
            key: detector.update(residuals.get(key, math.nan))
            for key, detector in self.detectors.items()
        }

    def reset(self, key: SensorKey, forget_window: bool = False) -> None:
        """Clear one sensor's statistics, e.g. after a correction was applied."""
        self.detectors[key].reset(forget_window)
