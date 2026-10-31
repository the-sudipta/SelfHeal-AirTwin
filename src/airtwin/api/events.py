"""The live twin behind the API: runs the engine over a stream and keeps what the web twin shows.

A background thread replays the dataset through :class:`~airtwin.twin.engine.TwinEngine`, first
at full speed past the calibration year and the drift baseline, then at one hourly tick per
``tick_seconds``. After each tick it keeps a JSON-ready frame (the same sensor fields as the
static replay), the twin's events and a network error against the original data. HTTP handlers
read this state and send commands (pause, inject a drift, mark a sensor recalibrated) through
the methods of :class:`TwinService`, which serialise access to the engine with one lock.

An injected drift is a demonstration, never hidden: it multiplies the incoming readings of one
sensor before the twin sees them, is logged as an ``inject`` event, and the frame keeps the
original value as ``truth`` so the error of the raw and of the published values can be shown.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from airtwin.config import ApiConfig
from airtwin.experiments.drift_injection import DriftSpec
from airtwin.stream.interface import Reading, StreamSource, Tick
from airtwin.twin.engine import EventKind, TwinEngine, TwinEvent
from airtwin.twin.state import SensorKey, TwinSnapshot

log = logging.getLogger(__name__)

INJECT = "inject"  # event kind of a demonstration drift, next to the engine's own kinds

OpenRun = Callable[[], tuple[TwinEngine, StreamSource]]


class Phase(StrEnum):
    """Where the live twin is in its run."""

    LOADING = "loading"  # reading and verifying the dataset
    CALIBRATING = "calibrating"  # fast-forward: models train, detectors learn their baseline
    RUNNING = "running"  # one tick per tick_seconds
    FINISHED = "finished"  # the stream ended
    FAILED = "failed"  # the run stopped with an error


@dataclass(frozen=True)
class Injection:
    """A demonstration drift applied to one sensor's incoming readings."""

    spec: DriftSpec

    def apply(self, when: datetime, value: float) -> float:
        """The reading the drifting sensor would report at ``when``."""
        return value * float(self.spec.factor([when])[0])


def number(value: float) -> float | None:
    """JSON-safe rounded number (NaN becomes null)."""
    return None if not math.isfinite(value) else round(float(value), 4)


def _rmse(errors: Iterable[float]) -> float:
    """Root mean square of the finite errors; NaN if there are none."""
    present = [e * e for e in errors if math.isfinite(e)]
    return math.sqrt(sum(present) / len(present)) if present else math.nan


class TwinService:
    """Runs one live twin and answers the API's questions about it."""

    def __init__(
        self, settings: ApiConfig, open_run: OpenRun, sleep: Callable[[float], bool] | None = None
    ) -> None:
        """Prepare the service; :meth:`start` opens the data and starts the run thread.

        ``open_run`` builds the engine and the stream (slow: it loads the dataset), so it runs
        in the background thread. ``sleep`` waits between ticks and returns True to stop
        early; by default it waits on the stop signal.
        """
        self._s = settings
        self._open_run = open_run
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._running = threading.Event()
        self._running.set()
        self._sleep = sleep or self._stop.wait
        self._thread: threading.Thread | None = None
        self._engine: TwinEngine | None = None
        self._keys: list[SensorKey] = []
        self.phase = Phase.LOADING
        self.error = ""
        self.version = 0  # increases with every tick or command, so clients see what is new
        self._hour = 0
        self._readings = 0
        self._frames: deque[dict[str, Any]] = deque(maxlen=settings.history_hours)
        self._events: deque[dict[str, Any]] = deque(maxlen=settings.event_log)
        self._event_id = 0
        self._errors: deque[tuple[list[float], list[float]]] = deque(
            maxlen=settings.rmse_window_hours
        )
        self._injections: dict[SensorKey, Injection] = {}

    # ---- run loop -------------------------------------------------------------------------

    def start(self) -> None:
        """Start the background run (once)."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="airtwin-live", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Ask the run to stop and wait for the thread."""
        self._stop.set()
        self._running.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def join(self, timeout: float | None = None) -> None:
        """Wait for the run to end (tests and one-shot runs)."""
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        """Open the data, then advance the twin tick by tick until the stream ends."""
        try:
            engine, stream = self._open_run()
            with self._lock:
                self._engine = engine
                self._keys = list(engine.keys)
                self.phase = Phase.CALIBRATING
                self.version += 1
            with stream:
                for tick in stream:
                    if self._stop.is_set():
                        return
                    live = self._hour >= self._s.fast_forward_hours
                    if live:
                        if self.phase is not Phase.RUNNING:
                            with self._lock:
                                self.phase = Phase.RUNNING
                        while not self._running.wait(self._s.poll_s * 5):
                            if self._stop.is_set():
                                return
                    self._advance(tick)
                    if live and self._s.tick_seconds and self._sleep(self._s.tick_seconds):
                        return
            with self._lock:
                self.phase = Phase.FINISHED
                self.version += 1
        except Exception as exc:  # the API must stay up and report the failure
            log.exception("live twin stopped")
            with self._lock:
                self.phase = Phase.FAILED
                self.error = f"{type(exc).__name__}: {exc}"
                self.version += 1

    def _advance(self, tick: Tick) -> None:
        """Feed one tick (with any injected drift) to the twin and record the result."""
        with self._lock:
            assert self._engine is not None
            truth = {
                SensorKey(r.site, v): float(x) for r in tick.readings for v, x in r.values.items()
            }
            result = self._engine.step(self._inject(tick))
            frame, errors = self._frame(result.snapshot, truth)
            self._frames.append(frame)
            self._errors.append(errors)
            self._readings += sum(1 for s in frame["sensors"] if s["raw"] is not None)
            for event in result.events:
                if event.kind is not EventKind.WATCH:
                    self._log_event(event)
            self._hour += 1
            self.version += 1

    def _inject(self, tick: Tick) -> Tick:
        """The tick as the drifting sensors would report it."""
        if not self._injections:
            return tick
        readings = []
        for r in tick.readings:
            values = dict(r.values)
            for variable in values:
                injection = self._injections.get(SensorKey(r.site, variable))
                if injection is not None:
                    values[variable] = injection.apply(tick.timestamp, values[variable])
            readings.append(Reading(r.site, values))
        return Tick(tick.timestamp, tuple(readings))

    def _frame(
        self, snapshot: TwinSnapshot, truth: dict[SensorKey, float]
    ) -> tuple[dict[str, Any], tuple[list[float], list[float]]]:
        """One hour of the twin, and the raw and published errors against the original data.

        The frame has the replay's sensor fields plus ``truth`` (the original reading) and
        ``injected``.
        """
        sensors: list[dict[str, Any]] = []
        raw_errors: list[float] = []
        pub_errors: list[float] = []
        for key in self._keys:
            s = snapshot.sensors[key]
            original = truth.get(key, math.nan)
            sensors.append(
                {
                    "site": key.site,
                    "variable": key.variable,
                    "raw": number(s.raw),
                    "expected": number(s.expected),
                    "corrected": number(s.corrected),
                    "truth": number(original),
                    "score": number(s.drift_score),
                    "status": s.status.value,
                    "offset": number(s.correction.offset),
                    "gain": number(s.correction.gain),
                    "injected": key in self._injections,
                }
            )
            raw_errors.append(s.raw - original)
            pub_errors.append(s.corrected - original)
        frame = {"hour": self._hour, "time": snapshot.timestamp.isoformat(), "sensors": sensors}
        return frame, (raw_errors, pub_errors)

    def _log_event(self, event: TwinEvent | None = None, **fields: Any) -> dict[str, Any]:
        """Append one event (from the engine, or a service event given as fields)."""
        self._event_id += 1
        if event is not None:
            fields = {
                "time": event.timestamp.isoformat(),
                "kind": event.kind.value,
                "sensor": str(event.key) if event.key else None,
                "message": event.message,
            }
        entry = {"id": self._event_id, **fields}
        self._events.append(entry)
        return entry

    # ---- queries --------------------------------------------------------------------------

    def _now(self) -> datetime | None:
        """Timestamp of the latest tick."""
        return datetime.fromisoformat(self._frames[-1]["time"]) if self._frames else None

    def status(self) -> dict[str, Any]:
        """Phase, clock and counters of the run."""
        with self._lock:
            now = self._now()
            return {
                "phase": self.phase.value,
                "running": self._running.is_set(),
                "error": self.error or None,
                "hour": self._hour,
                "time": now.isoformat() if now else None,
                "readings": self._readings,
                "sensors": [str(k) for k in self._keys],
                "tick_seconds": self._s.tick_seconds,
                "fast_forward_hours": self._s.fast_forward_hours,
                "version": self.version,
            }

    def network(self) -> dict[str, Any]:
        """RMSE of raw and published values against the original data over the recent window."""
        with self._lock:
            raw = [e for hour in self._errors for e in hour[0]]
            published = [e for hour in self._errors for e in hour[1]]
            return {
                "window_hours": len(self._errors),
                "rmse_raw": number(_rmse(raw)),
                "rmse_published": number(_rmse(published)),
            }

    def maintenance(self) -> list[dict[str, Any]]:
        """The ranked maintenance list."""
        with self._lock:
            if self._engine is None:
                return []
            return [
                {
                    "rank": i.rank,
                    "sensor": str(i.key),
                    "priority": number(i.priority),
                    "status": i.status.value,
                    "relative_error": number(i.relative_error),
                    "since": i.since.isoformat() if i.since else None,
                    "hours_faulty": number(i.hours_faulty),
                    "offset": number(i.correction.offset),
                    "gain": number(i.correction.gain),
                    "reason": i.reason,
                }
                for i in self._engine.maintenance_list()
            ]

    def events(self, after: int = 0) -> list[dict[str, Any]]:
        """Events with an id above ``after``, newest first."""
        with self._lock:
            return [e for e in reversed(self._events) if e["id"] > after]

    def injections(self) -> list[dict[str, Any]]:
        """The demonstration drifts currently applied."""
        with self._lock:
            return [
                {
                    "sensor": str(k),
                    "kind": i.spec.kind,
                    "onset": i.spec.onset.isoformat(),
                    "magnitude": i.spec.magnitude,
                }
                for k, i in sorted(self._injections.items())
            ]

    def history(self, hours: int | None = None) -> list[dict[str, Any]]:
        """The latest frames, oldest first."""
        with self._lock:
            frames = list(self._frames)
            return frames[-hours:] if hours else frames

    def state(self) -> dict[str, Any]:
        """Everything the web twin needs to draw itself."""
        with self._lock:
            return {
                "status": self.status(),
                "frame": self._frames[-1] if self._frames else None,
                "network": self.network(),
                "maintenance": self.maintenance(),
                "events": self.events(),
                "injections": self.injections(),
            }

    def update(self, last_event: int) -> dict[str, Any]:
        """What changed for a client that has seen events up to ``last_event``."""
        with self._lock:
            update = self.state()
            update["events"] = self.events(last_event)
            return update

    def what_if(self, sensor: str, days: Sequence[int]) -> dict[str, Any]:
        """Projected relative error of one sensor if it is not recalibrated."""
        key = self._key(sensor)
        with self._lock:
            assert self._engine is not None
            result = self._engine.what_if(key, sorted(set(days)))
            return {
                "sensor": str(key),
                "current_relative_error": number(result.current_relative_error),
                "rate_per_day": number(result.rate_per_day),
                "points_used": result.points_used,
                "basis": result.basis,
                "projections": [
                    {"days": p.horizon_days, "relative_error": number(p.relative_error)}
                    for p in result.projections
                ],
            }

    # ---- commands -------------------------------------------------------------------------

    def _key(self, sensor: str) -> SensorKey:
        """Parse a sensor name and check that the live twin has it.

        Raises:
            KeyError: If the twin is not ready or does not know the sensor.
        """
        try:
            key = SensorKey.parse(sensor)
        except ValueError as exc:
            raise KeyError(sensor) from exc
        with self._lock:
            if key not in self._keys:
                raise KeyError(sensor)
        return key

    def set_running(self, running: bool) -> dict[str, Any]:
        """Pause or resume the live ticks (fast-forward is never paused)."""
        if running:
            self._running.set()
        else:
            self._running.clear()
        with self._lock:
            self.version += 1
        return self.status()

    def inject(self, sensor: str) -> dict[str, Any]:
        """Start the configured demonstration drift on one sensor from the next hour.

        Raises:
            KeyError: If the sensor is unknown.
            RuntimeError: If the twin has not produced a tick yet.
        """
        key = self._key(sensor)
        settings = self._s.inject
        with self._lock:
            now = self._now()
            if now is None:
                raise RuntimeError("the twin has not started yet")
            spec = DriftSpec(
                key,
                settings.kind,
                now + timedelta(hours=1),
                settings.magnitude,
                settings.ramp_hours,
                settings.exp_rate,
            )
            self._injections[key] = Injection(spec)
            self.version += 1
            return self._log_event(
                time=now.isoformat(),
                kind=INJECT,
                sensor=str(key),
                message=(
                    f"demonstration drift injected: {settings.kind}, "
                    f"{settings.magnitude:+.0%} from the next hour"
                ),
            )

    def recalibrate(self, sensor: str) -> dict[str, Any]:
        """The field team serviced the sensor: any injected drift is gone, the twin resets it.

        Raises:
            KeyError: If the sensor is unknown.
        """
        key = self._key(sensor)
        with self._lock:
            assert self._engine is not None
            self._injections.pop(key, None)
            event = self._engine.mark_recalibrated(key)
            self.version += 1
            return self._log_event(event)
