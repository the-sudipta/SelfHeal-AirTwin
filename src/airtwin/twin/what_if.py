"""What-if: how wrong will a sensor be if it is not recalibrated for N more days?

Every time the self-healer fits a correction, the twin records the sensor's relative error at
its usual level (e.g. +0.12 = reads 12% high). The trend of these points over the recent
history window estimates how fast the error grows; the projection extends that trend
linearly to each horizon. With a single point there is no trend, so the error is projected
as constant and the result says so.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from airtwin.twin.state import SensorKey

SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class Projection:
    """Projected relative error after ``horizon_days`` without recalibration."""

    horizon_days: int
    relative_error: float


@dataclass(frozen=True)
class WhatIfResult:
    """Projection for one sensor, with the evidence it rests on."""

    key: SensorKey
    current_relative_error: float
    rate_per_day: float
    projections: tuple[Projection, ...]
    points_used: int
    basis: str


def project(
    key: SensorKey,
    history: Sequence[tuple[datetime, float]],
    now: datetime,
    horizons_days: Sequence[int],
    history_hours: int,
) -> WhatIfResult:
    """Project a sensor's relative error forward from its correction history.

    Args:
        key: The sensor.
        history: ``(time of fit, relative error)`` pairs, oldest first.
        now: The current time; horizons count from here.
        horizons_days: Days ahead to project.
        history_hours: Only fits within this many hours before ``now`` estimate the trend.
    """
    recent = []
    if history:
        window_start = now - timedelta(hours=history_hours)
        recent = [(t, e) for t, e in history if window_start <= t <= now]
    if not recent:
        return WhatIfResult(
            key,
            0.0,
            0.0,
            tuple(Projection(h, 0.0) for h in horizons_days),
            0,
            "no correction: sensor considered healthy",
        )
    current = recent[-1][1]
    days = np.array([(t - now).total_seconds() / SECONDS_PER_DAY for t, _ in recent])
    errors = np.array([e for _, e in recent])
    if len(recent) >= 2 and np.ptp(days) > 0:
        rate = float(np.polyfit(days, errors, 1)[0])
        span = float(np.ptp(days))
        basis = f"linear trend of {len(recent)} corrections over {span:.1f} days"
    else:
        rate = 0.0
        basis = "single correction: no growth rate yet, error held constant"
    return WhatIfResult(
        key,
        current,
        rate,
        tuple(Projection(h, current + rate * h) for h in horizons_days),
        len(recent),
        basis,
    )
