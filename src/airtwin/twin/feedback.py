"""Feedback from the virtual to the physical side: which sensor to recalibrate first, and why.

A sensor is listed when its drift is confirmed, or when its active correction changes its
readings by at least ``min_relative_error``. Priority grows with how wrong the sensor is and
how long it has been wrong:

``priority = |relative error| * (1 + days faulty / duration_weight_days)``

A confirmed drift that has no correction yet (too few pairs to fit) is ranked by its drift
score scaled to the listing threshold, so it is never dropped.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from airtwin.config import FeedbackSettings
from airtwin.twin.self_healer import relative_effect
from airtwin.twin.state import Correction, SensorKey, SensorStatus, TwinSnapshot

HOURS_PER_DAY = 24


@dataclass(frozen=True)
class MaintenanceItem:
    """One entry of the maintenance list sent to the city."""

    rank: int
    key: SensorKey
    priority: float
    status: SensorStatus
    relative_error: float  # +0.2: reads 20% too high
    since: datetime | None  # when drift was first confirmed
    hours_faulty: float
    correction: Correction
    reason: str


def _reason(relative_error: float, since: datetime | None, days: float, c: Correction) -> str:
    """A one-line explanation an operator can act on."""
    if relative_error == 0.0 and c.is_identity:
        return "drift confirmed, correction not yet estimated"
    direction = "high" if relative_error > 0 else "low"
    start = f" since {since:%Y-%m-%d %H:%M} ({days:.1f} days)" if since is not None else ""
    return (
        f"reads {abs(relative_error):.0%} too {direction}{start}; "
        f"correction offset {c.offset:+.2f}, gain {c.gain:.3f}"
    )


def rank_sensors(
    snapshot: TwinSnapshot,
    onsets: Mapping[SensorKey, datetime],
    levels: Mapping[SensorKey, float],
    settings: FeedbackSettings,
) -> list[MaintenanceItem]:
    """Build the maintenance list for one snapshot, highest priority first.

    Args:
        snapshot: The current twin state.
        onsets: Time drift was first confirmed, per sensor still faulty.
        levels: Each sensor's usual reading level, used to express the error in percent.
        settings: Listing threshold and duration weight.
    """
    candidates = []
    for state in snapshot:
        key = state.key
        rel = relative_effect(state.correction, levels.get(key, math.nan))
        drifting = state.status is SensorStatus.DRIFTING
        if not drifting and abs(rel) < settings.min_relative_error:
            continue
        since = onsets.get(key)
        hours = (snapshot.timestamp - since).total_seconds() / 3600 if since else 0.0
        days = hours / HOURS_PER_DAY
        if state.correction.is_identity:
            severity = settings.min_relative_error * max(state.drift_score, 1.0)
        else:
            severity = abs(rel)
        priority = severity * (1 + days / settings.duration_weight_days)
        candidates.append((priority, key, state, rel, since, hours, days))
    candidates.sort(key=lambda c: (-c[0], c[1]))
    return [
        MaintenanceItem(
            rank=i,
            key=key,
            priority=priority,
            status=state.status,
            relative_error=rel,
            since=since,
            hours_faulty=hours,
            correction=state.correction,
            reason=_reason(rel, since, days, state.correction),
        )
        for i, (priority, key, state, rel, since, hours, days) in enumerate(candidates, start=1)
    ]
