"""Self-healing: once drift is confirmed, estimate a linear correction online and keep it current.

A drifting low-cost sensor is modelled as ``raw = gain * true + offset``. The twin's expected
value stands in for the true value, so each sensor keeps a rolling window of
``(expected, raw)`` pairs. When drift is confirmed, the healer fits offset and gain on that
window with a robust two-pass least-squares fit (pairs far from the first fit are dropped),
then refits at a fixed interval while the correction is active, so a drift that keeps growing
stays corrected. The published value is ``(raw - offset) / gain``.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from airtwin.config import HealSettings
from airtwin.twin.state import IDENTITY, Correction, SensorKey

MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class FitResult:
    """A fitted correction and the number of pairs it rests on."""

    correction: Correction
    pairs: int


@dataclass(frozen=True)
class Proposal:
    """A candidate correction and the evidence for it on its fit window."""

    correction: Correction
    relative_error: float  # raw readings at the usual level are this much too high (+) or low
    improvement: float  # share by which the correction cuts the median absolute residual
    pairs: int


def fit_correction(
    expected: np.ndarray, raw: np.ndarray, settings: HealSettings
) -> FitResult | None:
    """Fit ``raw = gain * expected + offset`` robustly; None if too few usable pairs.

    A gain needs a range of concentrations, which a day or two rarely gives, so it is fitted only
    with at least ``gain_min_pairs`` pairs (and ``fit_gain`` true); otherwise, or when the
    expected values do not vary, only an offset is fitted (gain 1). The gain is clipped to the
    configured bounds.
    """
    usable = ~(np.isnan(expected) | np.isnan(raw))
    x, y = expected[usable], raw[usable]
    if len(x) < settings.min_pairs:
        return None
    with_gain = settings.fit_gain and len(x) >= settings.gain_min_pairs
    gain, offset = _linear_fit(x, y, settings, with_gain)
    residual = y - (gain * x + offset)
    spread = MAD_TO_SIGMA * float(np.median(np.abs(residual - np.median(residual))))
    if spread > 0:
        keep = np.abs(residual - np.median(residual)) <= settings.trim_mad * spread
        if keep.sum() >= settings.min_pairs:
            x, y = x[keep], y[keep]
            gain, offset = _linear_fit(x, y, settings, with_gain)
    return FitResult(Correction(offset=offset, gain=gain), len(x))


def _linear_fit(
    x: np.ndarray, y: np.ndarray, settings: HealSettings, with_gain: bool
) -> tuple[float, float]:
    """Least-squares gain and offset (centred, numerically stable), or a median offset only."""
    mean_x, mean_y = float(np.mean(x)), float(np.mean(y))
    var_x = float(np.mean((x - mean_x) ** 2))
    if with_gain and var_x > 0:
        slope = float(np.mean((x - mean_x) * (y - mean_y))) / var_x
        gain = float(np.clip(slope, settings.min_gain, settings.max_gain))
        return gain, mean_y - gain * mean_x
    return 1.0, float(np.median(y - x))


class SelfHealer:
    """Correction state of one sensor."""

    def __init__(self, settings: HealSettings) -> None:
        """Start with no correction and an empty pair window."""
        self._s = settings
        self._expected: deque[float] = deque(maxlen=settings.fit_hours)
        self._raw: deque[float] = deque(maxlen=settings.fit_hours)
        self.correction: Correction = IDENTITY
        self.active = False
        self._hours_since_fit = 0

    def observe(self, raw: float, expected: float) -> None:
        """Remember one hour's pair; called every hour, healthy or not."""
        self._raw.append(raw)
        self._expected.append(expected)
        if self.active:
            self._hours_since_fit += 1

    def _window(self, window: int | None) -> tuple[np.ndarray, np.ndarray]:
        """The last ``window`` (expected, raw) pairs, or all kept pairs if None."""
        size = len(self._raw) if window is None else min(window, len(self._raw))
        expected = np.asarray(self._expected, dtype="float64")[len(self._expected) - size :]
        raw = np.asarray(self._raw, dtype="float64")[len(self._raw) - size :]
        return expected, raw

    def propose(self, window: int | None = None) -> Proposal | None:
        """Fit a candidate correction on the last ``window`` pairs without applying it.

        The engine passes the hours that belong to the current drift, so pairs from before the
        drift do not dilute the fit. Returns None if too few usable pairs.
        """
        expected, raw = self._window(window)
        result = fit_correction(expected, raw, self._s)
        if result is None:
            return None
        usable = ~(np.isnan(expected) | np.isnan(raw))
        before = float(np.median(np.abs(raw[usable] - expected[usable])))
        after = float(np.median(np.abs(result.correction.apply(raw[usable]) - expected[usable])))
        improvement = 1 - after / before if before > 0 else 0.0
        effect = relative_effect(result.correction, self.typical_level())
        return Proposal(result.correction, effect, improvement, result.pairs)

    def accept(self, correction: Correction) -> None:
        """Publish a correction from now on."""
        self.correction = correction
        self.active = True
        self._hours_since_fit = 0

    def deactivate(self) -> None:
        """Stop correcting (the shift has gone), keeping the pair window."""
        self.correction = IDENTITY
        self.active = False
        self._hours_since_fit = 0

    @property
    def refit_due(self) -> bool:
        """True when a correction is active and the refit interval has passed."""
        return self.active and self._hours_since_fit >= self._s.refit_hours

    def heal(self, window: int | None = None) -> Correction | None:
        """Fit and immediately apply a correction; None if too few usable pairs."""
        proposal = self.propose(window)
        if proposal is None:
            return None
        self.accept(proposal.correction)
        return proposal.correction

    def maybe_refit(self, window: int | None = None) -> Correction | None:
        """Refit and apply if a correction is active and the refit interval has passed."""
        return self.heal(window) if self.refit_due else None

    def typical_level(self) -> float:
        """Median expected value in the pair window: the sensor's usual reading level."""
        values = np.asarray(self._expected, dtype="float64")
        values = values[~np.isnan(values)]
        return float(np.median(values)) if len(values) else math.nan

    def clear(self) -> None:
        """Forget the correction and the pair window (the sensor was recalibrated)."""
        self._expected.clear()
        self._raw.clear()
        self.correction = IDENTITY
        self.active = False
        self._hours_since_fit = 0


class SelfHealerBank:
    """One self-healer per sensor."""

    def __init__(self, keys: Iterable[SensorKey], settings: HealSettings) -> None:
        """Create a healer for every key."""
        self.healers = {key: SelfHealer(settings) for key in keys}

    def __getitem__(self, key: SensorKey) -> SelfHealer:
        """The healer of one sensor."""
        return self.healers[key]


def relative_effect(correction: Correction, level: float) -> float:
    """How much the correction changes a reading at ``level``, relative to that level.

    ``0.2`` means raw readings at this level are 20% too high (negative: too low).
    """
    if correction.is_identity or math.isnan(level) or level == 0:
        return 0.0
    raw_at_level = correction.gain * level + correction.offset
    return (raw_at_level - level) / abs(level)
