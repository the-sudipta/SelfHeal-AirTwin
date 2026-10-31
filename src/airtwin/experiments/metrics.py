"""Error and detection metrics.

Detection is scored per injected drift and per alarm:

* a drift is **detected** at the first alarm on its sensor at or after its onset; the
  **delay** is the time from onset to that alarm;
* every other alarm is a **false alarm**: on a sensor that never drifts, or on a drifting
  sensor before its onset (repeated alarms on an already detected drift are not counted);
* precision = detected / (detected + false alarms), recall = detected / drifts, F1 their
  harmonic mean; false alarms are also given per 1,000 monitored sensor-hours.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from airtwin.experiments.drift_injection import DriftSpec
from airtwin.twin.state import SensorKey


def rmse(estimate: np.ndarray, truth: np.ndarray) -> float:
    """Root mean squared error over the positions where both are present."""
    ok = ~(np.isnan(estimate) | np.isnan(truth))
    return float(np.sqrt(np.mean((estimate[ok] - truth[ok]) ** 2))) if ok.any() else math.nan


def mae(estimate: np.ndarray, truth: np.ndarray) -> float:
    """Mean absolute error over the positions where both are present."""
    ok = ~(np.isnan(estimate) | np.isnan(truth))
    return float(np.mean(np.abs(estimate[ok] - truth[ok]))) if ok.any() else math.nan


@dataclass(frozen=True)
class DetectionScore:
    """Detection quality of one run."""

    drifts: int
    detected: int
    false_alarms: int
    precision: float
    recall: float
    f1: float
    false_alarms_per_1000h: float
    delays_hours: tuple[float, ...]  # one per detected drift

    @property
    def median_delay_hours(self) -> float:
        """Median delay of the detected drifts (NaN if none)."""
        return float(np.median(self.delays_hours)) if self.delays_hours else math.nan


def score_detection(
    alarms: Sequence[tuple[SensorKey, datetime]],
    drifts: Sequence[DriftSpec],
    window: tuple[datetime, datetime],
    sensors: int,
) -> DetectionScore:
    """Score alarms that fall inside the evaluation ``window`` against the injected drifts."""
    onsets = {d.key: d.onset for d in drifts}
    first: dict[SensorKey, datetime] = {}
    false_alarms = 0
    for key, when in sorted(alarms, key=lambda a: (a[1], a[0])):
        if not window[0] <= when <= window[1]:
            continue
        onset = onsets.get(key)
        if onset is not None and when >= onset:
            first.setdefault(key, when)
        else:
            false_alarms += 1
    delays = tuple(
        (first[d.key] - d.onset).total_seconds() / 3600 for d in drifts if d.key in first
    )
    detected = len(delays)
    precision = detected / (detected + false_alarms) if detected + false_alarms else math.nan
    recall = detected / len(drifts) if drifts else math.nan
    f1 = (
        2 * precision * recall / (precision + recall)
        if not (math.isnan(precision) or math.isnan(recall)) and precision + recall > 0
        else 0.0
    )
    hours = (window[1] - window[0]).total_seconds() / 3600
    per_1000h = 1000 * false_alarms / (hours * sensors) if hours > 0 and sensors else math.nan
    return DetectionScore(
        len(drifts), detected, false_alarms, precision, recall, f1, per_1000h, delays
    )
