"""Inject known, synthetic sensor drift into clean data, so detection and healing can be scored.

A drifting sensor reads ``true * factor(t)`` with ``factor = 1 + magnitude * shape(t)``:

* **step**: ``shape = 1`` from the onset on;
* **linear**: ``shape`` rises linearly from 0 to 1 over ``ramp_hours``, then holds;
* **exponential**: ``shape = (exp(r x) - 1) / (exp(r) - 1)`` with ``x`` the share of the ramp
  elapsed, so the drift starts slowly and accelerates, then holds.

The magnitude is signed: a sensor may read too high or too low.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from airtwin.stream.memory_stream import SITE, TIMESTAMP
from airtwin.twin.state import SensorKey

STEP, LINEAR, EXPONENTIAL = "step", "linear", "exponential"


@dataclass(frozen=True)
class DriftSpec:
    """One injected drift: which sensor, what kind, from when, and how large."""

    key: SensorKey
    kind: str
    onset: datetime
    magnitude: float  # signed relative size at full strength, e.g. +0.3
    ramp_hours: int
    exp_rate: float

    def shape(self, hours_since_onset: np.ndarray) -> np.ndarray:
        """Drift strength in [0, 1] for each number of hours after the onset (0 before it)."""
        x = np.clip(hours_since_onset / self.ramp_hours, 0.0, 1.0)
        if self.kind == STEP:
            shape = np.ones_like(x)
        elif self.kind == LINEAR:
            shape = x
        elif self.kind == EXPONENTIAL:
            shape = np.expm1(self.exp_rate * x) / math.expm1(self.exp_rate)
        else:
            raise ValueError(f"unknown drift kind {self.kind!r}")
        return np.where(hours_since_onset >= 0, shape, 0.0)

    def factor(self, timestamps: Sequence[datetime] | pd.Series) -> np.ndarray:
        """Multiplicative factor applied to the true readings at the given times."""
        hours = (
            pd.to_datetime(pd.Series(timestamps)) - pd.Timestamp(self.onset)
        ).dt.total_seconds()
        return 1.0 + self.magnitude * self.shape(hours.to_numpy() / 3600)

    def relative_error(self, when: datetime) -> float:
        """True relative error of the drifting sensor at one time."""
        return float(self.factor([when])[0] - 1.0)


def plan_drifts(
    rng: np.random.Generator,
    sites: Sequence[str],
    variable: str,
    kind: str,
    count: int,
    window: tuple[datetime, datetime],
    magnitude: tuple[float, float],
    ramp_hours: int,
    exp_rate: float,
) -> list[DriftSpec]:
    """Draw ``count`` distinct sites, onsets uniform in ``window`` and signed magnitudes."""
    if count > len(sites):
        raise ValueError("more drifting sensors than sites")
    chosen = rng.choice(sorted(sites), size=count, replace=False)
    span_hours = int((window[1] - window[0]).total_seconds() // 3600)
    specs = []
    for site in sorted(chosen):
        onset = window[0] + timedelta(hours=int(rng.integers(0, max(span_hours, 1))))
        size = float(rng.uniform(*magnitude)) * (1 if rng.random() < 0.5 else -1)
        specs.append(
            DriftSpec(SensorKey(str(site), variable), kind, onset, size, ramp_hours, exp_rate)
        )
    return specs


def inject(frame: pd.DataFrame, specs: Sequence[DriftSpec]) -> pd.DataFrame:
    """Return a copy of a long table in which each drifting sensor's readings are scaled."""
    out = frame.copy()
    for spec in specs:
        rows = out[SITE] == spec.key.site
        out.loc[rows, spec.key.variable] = out.loc[
            rows, spec.key.variable
        ].to_numpy() * spec.factor(out.loc[rows, TIMESTAMP])
    return out
