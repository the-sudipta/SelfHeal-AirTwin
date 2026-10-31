"""Typed, immutable state of the twin: one record per sensor, one snapshot per hour.

These types are the interface between the twin parts. Every part reads a snapshot and
returns new values; only the engine assembles the next snapshot.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

SEPARATOR = ":"


class SensorStatus(StrEnum):
    """Lifecycle of one sensor as seen by the twin."""

    WARMUP = "warmup"  # expected-value model not trained yet
    HEALTHY = "healthy"  # residual within normal range
    WATCH = "watch"  # drift score rising, no alarm yet
    DRIFTING = "drifting"  # drift confirmed, correction being estimated
    HEALED = "healed"  # correction active and residual back to normal


@dataclass(frozen=True, order=True)
class SensorKey:
    """Identifies one measured variable at one site, e.g. ``Dongsi:pm25``."""

    site: str
    variable: str

    def __post_init__(self) -> None:
        """Reject names that would make the text form ambiguous."""
        if not self.site or not self.variable or SEPARATOR in self.site + self.variable:
            raise ValueError(f"invalid sensor key {self.site!r}, {self.variable!r}")

    def __str__(self) -> str:
        """Return ``site:variable``."""
        return f"{self.site}{SEPARATOR}{self.variable}"

    @classmethod
    def parse(cls, text: str) -> SensorKey:
        """Build a key from its ``site:variable`` text form."""
        site, sep, variable = text.partition(SEPARATOR)
        if not sep:
            raise ValueError(f"sensor key {text!r} lacks {SEPARATOR!r}")
        return cls(site, variable)


@dataclass(frozen=True)
class Correction:
    """Linear correction of a drifted sensor: ``corrected = (raw - offset) / gain``."""

    offset: float = 0.0
    gain: float = 1.0

    def __post_init__(self) -> None:
        """A gain of zero or below would invert or erase the signal."""
        if not self.gain > 0:
            raise ValueError(f"gain must be positive, got {self.gain}")

    @property
    def is_identity(self) -> bool:
        """True when the correction leaves readings unchanged."""
        return self.offset == 0.0 and self.gain == 1.0

    def apply(self, raw: float) -> float:
        """Correct one reading; NaN stays NaN."""
        return (raw - self.offset) / self.gain


IDENTITY = Correction()


@dataclass(frozen=True)
class SensorState:
    """Everything the twin knows about one sensor after one hour."""

    key: SensorKey
    raw: float = math.nan
    expected: float = math.nan
    drift_score: float = 0.0
    status: SensorStatus = SensorStatus.WARMUP
    correction: Correction = IDENTITY

    @property
    def residual(self) -> float:
        """Raw minus expected; NaN if either is missing."""
        return self.raw - self.expected

    @property
    def corrected(self) -> float:
        """The published value: the raw reading with the active correction applied."""
        return self.correction.apply(self.raw)

    def with_reading(self, raw: float, expected: float) -> SensorState:
        """Return a copy holding a new hour's reading and expected value."""
        return replace(self, raw=raw, expected=expected)


@dataclass(frozen=True)
class TwinSnapshot:
    """The twin's view of every sensor at one timestamp."""

    timestamp: datetime
    sensors: Mapping[SensorKey, SensorState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze the mapping and check that each state is stored under its own key."""
        frozen = MappingProxyType(dict(sorted(self.sensors.items())))
        for key, state in frozen.items():
            if state.key != key:
                raise ValueError(f"state for {state.key} stored under {key}")
        object.__setattr__(self, "sensors", frozen)

    def __iter__(self) -> Iterator[SensorState]:
        """Iterate over sensor states in key order."""
        return iter(self.sensors.values())

    def __len__(self) -> int:
        """Number of sensors in the snapshot."""
        return len(self.sensors)

    def sites(self) -> list[str]:
        """Site names present in the snapshot, sorted."""
        return sorted({k.site for k in self.sensors})

    def at_site(self, site: str) -> list[SensorState]:
        """States of every sensor at one site, in key order."""
        return [s for k, s in self.sensors.items() if k.site == site]

    def with_status(self, status: SensorStatus) -> list[SensorState]:
        """States currently in the given status."""
        return [s for s in self.sensors.values() if s.status == status]
