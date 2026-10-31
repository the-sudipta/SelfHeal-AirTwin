"""The typed contract every stream backend implements: readings, ticks and the source protocol."""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType, TracebackType
from typing import Protocol, Self, runtime_checkable


class StreamError(RuntimeError):
    """Raised when a stream produces data that breaks the contract."""


@dataclass(frozen=True)
class Reading:
    """All values one site reports for one hour. Missing values are NaN."""

    site: str
    values: Mapping[str, float]

    def __post_init__(self) -> None:
        """Freeze the values mapping so a reading cannot be changed after creation."""
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    def observed(self) -> dict[str, float]:
        """Return only the values that are present (not NaN)."""
        return {k: v for k, v in self.values.items() if not math.isnan(v)}


@dataclass(frozen=True)
class Tick:
    """One twinning cycle: every site's reading for one timestamp, sorted by site."""

    timestamp: datetime
    readings: tuple[Reading, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Check that sites are unique and sorted, so consumers can rely on the order."""
        sites = [r.site for r in self.readings]
        if sites != sorted(set(sites)):
            raise StreamError(f"tick {self.timestamp}: sites must be unique and sorted")

    @property
    def sites(self) -> tuple[str, ...]:
        """Site names in this tick, in order."""
        return tuple(r.site for r in self.readings)

    def reading(self, site: str) -> Reading:
        """Return the reading of one site.

        Raises:
            KeyError: If the site is not part of this tick.
        """
        for r in self.readings:
            if r.site == site:
                return r
        raise KeyError(site)


@runtime_checkable
class StreamSource(Protocol):
    """A source of ticks in strictly increasing time order.

    Backends are context managers: leaving the ``with`` block releases their resources,
    and iteration after :meth:`close` yields nothing.
    """

    name: str

    def __iter__(self) -> Iterator[Tick]:
        """Yield ticks in strictly increasing timestamp order."""
        ...

    def close(self) -> None:
        """Release resources; further iteration yields nothing."""
        ...

    def __enter__(self) -> Self:
        """Return the source itself."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the source."""
        ...


def check_order(ticks: Iterator[Tick]) -> Iterator[Tick]:
    """Pass ticks through, raising :class:`StreamError` if time does not strictly increase."""
    last: datetime | None = None
    for tick in ticks:
        if last is not None and tick.timestamp <= last:
            raise StreamError(f"tick {tick.timestamp} is not after {last}")
        last = tick.timestamp
        yield tick
