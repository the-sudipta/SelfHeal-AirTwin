"""The twin engine: the one place that wires expected value, drift, healing, feedback and what-if.

Each hourly tick passes through the same cycle for every sensor:

1. **Virtual entity** — the expected-value bank predicts what the sensor should read.
2. **Self-healing input** — the active correction (identity if none) turns the raw reading
   into the published corrected value; the healer remembers the ``(expected, raw)`` pair.
3. **Drift detection** — the detector watches the residual of the *corrected* value, so a
   working correction looks healthy and a growing drift is noticed again.
4. **Healing** — on confirmed drift the healer fits a correction and the detector is reset;
   while a correction is active it is refitted at a fixed interval.
5. **Feedback** — on request, the maintenance list ranks the sensors to recalibrate, and the
   what-if projection extends each sensor's error trend; marking a sensor recalibrated clears
   its correction (the virtual-to-physical loop).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from airtwin.config import Config, TargetSpec, TwinConfig
from airtwin.stream.interface import Tick
from airtwin.twin.drift_detector import DriftDetectorBank, DriftReading
from airtwin.twin.expected_model import ExpectedValueBank, build_specs, flatten
from airtwin.twin.feedback import MaintenanceItem, rank_sensors
from airtwin.twin.self_healer import Proposal, SelfHealerBank, relative_effect
from airtwin.twin.state import Correction, SensorKey, SensorState, SensorStatus, TwinSnapshot
from airtwin.twin.what_if import WhatIfResult, project


class EventKind(StrEnum):
    """What happened to the twin or to one sensor."""

    CALIBRATED = "calibrated"  # expected-value models trained
    WATCH = "watch"  # drift score crossed the watch level
    DETECT = "detect"  # drift confirmed
    HEAL = "heal"  # correction estimated and published
    REFIT = "refit"  # active correction updated
    DISMISSED = "dismissed"  # confirmed alarm without a convincing correction: not a drift
    RECOVERED = "recovered"  # the shift disappeared and the correction was retired
    RECALIBRATED = "recalibrated"  # the physical sensor was serviced


@dataclass(frozen=True)
class TwinEvent:
    """One entry of the twin's event log."""

    timestamp: datetime
    kind: EventKind
    key: SensorKey | None
    message: str


@dataclass(frozen=True)
class StepResult:
    """The twin after one tick, and what happened during it."""

    snapshot: TwinSnapshot
    events: tuple[TwinEvent, ...]


class TwinEngine:
    """Runs the twin for one dataset."""

    def __init__(
        self,
        twin: TwinConfig,
        target: TargetSpec,
        sites: Sequence[str],
        bank: ExpectedValueBank | None = None,
    ) -> None:
        """Create models, detectors and healers for every twinned sensor.

        A calibrated ``bank`` (e.g. shared by many experiment runs on the same calibration
        data) skips the calibration window: the stream should then start after it.
        """
        self._cfg = twin
        specs = build_specs(sites, target)
        self.keys = [s.target for s in specs]
        # dependents[k]: sensors whose expected-value model takes k's reading as an input
        self._dependents: dict[SensorKey, list[SensorKey]] = {k: [] for k in self.keys}
        for spec in specs:
            for feature in spec.features:
                if feature in {str(k) for k in self.keys}:
                    self._dependents[SensorKey.parse(feature)].append(spec.target)
        self._bank = bank or ExpectedValueBank(
            specs, twin.model, target.calibration_hours, twin.min_training_rows
        )
        self._detectors = DriftDetectorBank(self.keys, twin.drift)
        self._healers = SelfHealerBank(self.keys, twin.heal)
        self._onsets: dict[SensorKey, datetime] = {}
        self._history: dict[SensorKey, list[tuple[datetime, float]]] = {k: [] for k in self.keys}
        self._statuses = {k: SensorStatus.WARMUP for k in self.keys}
        self.snapshot: TwinSnapshot | None = None

    @property
    def bank(self) -> ExpectedValueBank:
        """The expected-value models (read-only use, e.g. for baselines)."""
        return self._bank

    @classmethod
    def for_dataset(cls, cfg: Config, dataset: str, sites: Iterable[str]) -> TwinEngine:
        """Build an engine from the full configuration for one dataset and its sites."""
        return cls(cfg.twin, cfg.twin.target(dataset), sorted(sites))

    def _expected(self, row: dict[str, float]) -> dict[SensorKey, float]:
        """Expected values with trust substitution, so one faulty sensor cannot mislead others.

        A sensor can be another sensor's input (a neighbour). A sensor with confirmed drift or an
        active correction is untrusted. Untrusted sensors are predicted first, from physical
        inputs (each untrusted neighbour enters with its corrected reading, so no virtual value
        is ever computed only from other virtual values). Then every trusted sensor is predicted
        with the untrusted neighbours replaced by their *virtual* values. Sensors merely on
        watch stay trusted: a watch is frequent and usually passes. Each model runs once.
        """
        if not self._cfg.trust_substitution:
            return self._bank.predict(row, self.keys)
        inputs = dict(row)
        untrusted = [
            k
            for k in self.keys
            if self._healers[k].active or self._statuses[k] is SensorStatus.DRIFTING
        ]
        for key in untrusted:
            inputs[str(key)] = self._healers[key].correction.apply(row.get(str(key), math.nan))
        expected = self._bank.predict(inputs, untrusted)
        for key in untrusted:
            inputs[str(key)] = expected[key]
        trusted = [k for k in self.keys if k not in expected]
        expected.update(self._bank.predict(inputs, trusted))
        return expected

    def _fit_window(self, key: SensorKey, now: datetime) -> int:
        """Hours of pairs that belong to the current drift: since onset, plus detection lag.

        Drift becomes visible only after the rolling median and the confirmation streak, so the
        window reaches back ``smooth_hours + confirm_hours`` before the confirmed onset. It is
        never shorter than ``min_pairs`` and never longer than ``fit_hours``.
        """
        drift, heal = self._cfg.drift, self._cfg.heal
        onset = self._onsets.get(key, now)
        since = int((now - onset).total_seconds() // 3600)
        window = since + drift.smooth_hours + drift.confirm_hours
        return max(heal.min_pairs, min(window, heal.fit_hours))

    def _record_fit(self, key: SensorKey, when: datetime, correction: Correction) -> float:
        """Store the relative error implied by a new correction for the what-if history."""
        rel = relative_effect(correction, self._healers[key].typical_level())
        self._history[key].append((when, rel))
        return rel

    def _convincing(self, proposal: Proposal, direction: int) -> bool:
        """A correction is applied only if it is large, clearly better, and points the right way."""
        heal = self._cfg.heal
        sign_ok = direction == 0 or (proposal.relative_error > 0) == (direction > 0)
        return (
            abs(proposal.relative_error) >= heal.min_effect
            and proposal.improvement >= heal.min_improvement
            and sign_ok
        )

    def _heal(self, key: SensorKey, now: datetime, direction: int) -> list[TwinEvent]:
        """Act on a confirmed drift: apply a convincing correction, or dismiss the alarm.

        A false alarm on a healthy sensor fits only model error, which yields a small or
        unhelpful correction; such alarms are dismissed and their evidence is wiped, so healthy
        sensors are not "corrected". With too few pairs the decision waits for more hours.
        """
        healer = self._healers[key]
        detector = self._detectors.detectors[key]
        proposal = healer.propose(self._fit_window(key, now))
        if proposal is None:
            return []
        # with a correction already active, the new fit replaces it, so the direction of the
        # residual after the old correction says nothing about the sign of the new one
        if self._convincing(proposal, 0 if healer.active else direction):
            healer.accept(proposal.correction)
            detector.reset()
            rel = self._record_fit(key, now, proposal.correction)
            c = proposal.correction
            message = f"correction offset {c.offset:+.2f}, gain {c.gain:.3f} ({rel:+.1%})"
            return [TwinEvent(now, EventKind.HEAL, key, message)]
        detector.reset(forget_window=True)
        if not healer.active:
            self._onsets.pop(key, None)
        message = (
            f"alarm dismissed: shift {proposal.relative_error:+.1%}, "
            f"fit improves residual by {proposal.improvement:.0%}"
        )
        return [TwinEvent(now, EventKind.DISMISSED, key, message)]

    def _refit(self, key: SensorKey, now: datetime) -> list[TwinEvent]:
        """Update an active correction, or retire it once the shift has gone."""
        healer = self._healers[key]
        proposal = healer.propose(self._fit_window(key, now))
        if proposal is not None and self._convincing(proposal, 0):
            healer.accept(proposal.correction)
            rel = self._record_fit(key, now, proposal.correction)
            return [TwinEvent(now, EventKind.REFIT, key, f"correction updated, {rel:+.1%}")]
        healer.deactivate()
        self._detectors.reset(key, forget_window=True)
        self._onsets.pop(key, None)
        self._history[key] = []
        return [TwinEvent(now, EventKind.RECOVERED, key, "shift gone, correction retired")]

    def _sensor_step(
        self, key: SensorKey, now: datetime, raw: float, expected: float
    ) -> tuple[SensorState, list[TwinEvent]]:
        """Run one sensor through correction, detection and healing for one hour."""
        events: list[TwinEvent] = []
        healer = self._healers[key]
        detector = self._detectors.detectors[key]
        healer.observe(raw, expected)
        if healer.refit_due:
            events.extend(self._refit(key, now))
        residual = healer.correction.apply(raw) - expected
        reading: DriftReading = detector.update(residual)
        if reading.confirmed_now:
            self._onsets.setdefault(key, now)
            way = "high" if reading.direction > 0 else "low"
            events.append(TwinEvent(now, EventKind.DETECT, key, f"drift confirmed, reads {way}"))
        if detector.confirmed and self._cfg.heal.enabled:
            events.extend(self._heal(key, now, reading.direction))
        elif reading.confirmed_now:
            # detect-only mode: the alarm goes to the operator and monitoring restarts, so a
            # lasting drift keeps raising alarms instead of one alarm forever
            detector.reset(forget_window=True)
        status = self._status(reading, healer.active, detector.confirmed or reading.confirmed_now)
        if status is SensorStatus.WATCH and self._statuses[key] is not SensorStatus.WATCH:
            events.append(TwinEvent(now, EventKind.WATCH, key, f"drift score {reading.score:.2f}"))
        self._statuses[key] = status
        state = SensorState(key, raw, expected, reading.score, status, healer.correction)
        return state, events

    @staticmethod
    def _status(reading: DriftReading, corrected: bool, drifting: bool) -> SensorStatus:
        """Combine the detector verdict with the correction state."""
        if reading.status is SensorStatus.WARMUP:
            return SensorStatus.WARMUP
        if drifting:
            return SensorStatus.DRIFTING
        if corrected and reading.status is SensorStatus.HEALTHY:
            return SensorStatus.HEALED
        return reading.status

    def step(self, tick: Tick) -> StepResult:
        """Advance the twin by one hour."""
        row = flatten(tick)
        was_calibrated = self._bank.calibrated
        # before calibration, observe() collects the window and trains at its last hour
        expected = self._expected(row) if was_calibrated else self._bank.observe(row)
        events: list[TwinEvent] = []
        if self._bank.calibrated and not was_calibrated:
            trained = len(self._bank.trained_keys())
            events.append(
                TwinEvent(
                    tick.timestamp,
                    EventKind.CALIBRATED,
                    None,
                    f"expected-value models trained for {trained} of {len(self.keys)} sensors",
                )
            )
        states = {}
        confirmed: list[SensorKey] = []
        for key in self.keys:
            raw = row.get(str(key), math.nan)
            if not was_calibrated:  # predictions start the hour after calibration
                states[key] = SensorState(key, raw=raw)
                continue
            states[key], sensor_events = self._sensor_step(key, tick.timestamp, raw, expected[key])
            events.extend(sensor_events)
            confirmed += [e.key for e in sensor_events if e.kind is EventKind.DETECT and e.key]
        self._isolate(confirmed)
        self.snapshot = TwinSnapshot(tick.timestamp, states)
        return StepResult(self.snapshot, tuple(events))

    def _isolate(self, faulty: Iterable[SensorKey]) -> None:
        """Fault isolation: wipe drift evidence that was built on a now-confirmed faulty input.

        Until a drifting sensor is confirmed, its raw reading feeds its neighbours' models and
        shifts their residuals too. Once it is confirmed (and from now on substituted by its
        virtual value), every dependent sensor that is not itself drifting restarts its drift
        statistics and rolling window, so only clean evidence counts. A dependent that truly
        drifts as well will be confirmed again on clean inputs.
        """
        if not self._cfg.trust_substitution:
            return
        for key in faulty:
            for dependent in self._dependents[key]:
                detector = self._detectors.detectors[dependent]
                if not detector.confirmed and not self._healers[dependent].active:
                    self._detectors.reset(dependent, forget_window=True)

    def run(self, ticks: Iterable[Tick]) -> Iterator[StepResult]:
        """Advance the twin over a whole stream."""
        for tick in ticks:
            yield self.step(tick)

    def maintenance_list(self) -> list[MaintenanceItem]:
        """Sensors to recalibrate, highest priority first."""
        if self.snapshot is None:
            return []
        levels = {k: self._healers[k].typical_level() for k in self.keys}
        return rank_sensors(self.snapshot, self._onsets, levels, self._cfg.feedback)

    def what_if(self, key: SensorKey, horizons_days: Sequence[int] | None = None) -> WhatIfResult:
        """Project a sensor's error if it is not recalibrated (configured horizons by default)."""
        now = self.snapshot.timestamp if self.snapshot else datetime.min
        settings = self._cfg.what_if
        return project(
            key,
            self._history[key],
            now,
            horizons_days or settings.horizons_days,
            settings.history_hours,
            settings.min_trend_r2,
        )

    def mark_recalibrated(self, key: SensorKey) -> TwinEvent:
        """The physical sensor was serviced: clear its correction, detector and history."""
        if key not in self._healers.healers:
            raise KeyError(key)
        self._healers[key].clear()
        self._detectors.reset(key)
        self._onsets.pop(key, None)
        self._history[key] = []
        self._statuses[key] = SensorStatus.HEALTHY
        now = self.snapshot.timestamp if self.snapshot else datetime.min
        return TwinEvent(
            now, EventKind.RECALIBRATED, key, "sensor recalibrated, correction cleared"
        )
