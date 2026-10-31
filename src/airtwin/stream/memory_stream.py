"""In-process replay of a cleaned data frame as an hourly stream (the default backend)."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from types import TracebackType
from typing import Self

import numpy as np
import pandas as pd

from airtwin.stream.interface import Reading, StreamError, Tick, check_order

TIMESTAMP = "timestamp"
SITE = "site"


class MemoryStream:
    """Replay a long table (one row per site and hour) tick by tick.

    Rows are grouped by timestamp; each group becomes one :class:`Tick` whose readings
    are sorted by site. Values keep NaN for missing measurements.
    """

    def __init__(
        self,
        frame: pd.DataFrame,
        value_columns: Sequence[str],
        *,
        name: str = "memory",
        delay_s: float = 0.0,
        limit: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Prepare the replay.

        Args:
            frame: Long table with ``timestamp`` and ``site`` columns plus the value columns.
            value_columns: Columns copied into each reading, in this order.
            name: Name of this source, shown in logs and results.
            delay_s: Pause after each tick; 0 replays as fast as possible.
            limit: Stop after this many ticks; ``None`` replays everything.
            sleep: Function used to pause; replaced in tests.

        Raises:
            StreamError: If columns are missing or a site appears twice in one hour.
        """
        missing = {TIMESTAMP, SITE, *value_columns} - set(frame.columns)
        if missing:
            raise StreamError(f"frame lacks columns {sorted(missing)}")
        if delay_s < 0 or (limit is not None and limit < 0):
            raise StreamError("delay_s and limit must not be negative")
        ordered = frame.sort_values([TIMESTAMP, SITE], ignore_index=True)
        if ordered.duplicated([TIMESTAMP, SITE]).any():
            raise StreamError("a site appears more than once in the same hour")
        self.name = name
        self.value_columns = tuple(value_columns)
        self._times = ordered[TIMESTAMP].to_numpy()
        self._sites = ordered[SITE].astype(str).to_numpy()
        self._values = ordered[list(self.value_columns)].to_numpy(dtype="float64")
        self._delay_s = delay_s
        self._limit = limit
        self._sleep = sleep
        self._closed = False

    @classmethod
    def from_wide(
        cls, frame: pd.DataFrame, site: str, value_columns: Sequence[str], **kwargs: object
    ) -> MemoryStream:
        """Build a stream from a single-site table indexed by timestamp (e.g. UCI Air Quality)."""
        long = frame.reset_index().rename(columns={frame.index.name or "index": TIMESTAMP})
        long.insert(1, SITE, site)
        return cls(long, value_columns, **kwargs)  # type: ignore[arg-type]

    @property
    def n_rows(self) -> int:
        """Number of site-hour rows available for replay."""
        return len(self._times)

    def _ticks(self) -> Iterator[Tick]:
        """Yield one tick per distinct timestamp."""
        if self.n_rows == 0:
            return
        starts = np.flatnonzero(np.r_[True, self._times[1:] != self._times[:-1]])
        ends = np.r_[starts[1:], self.n_rows]
        for emitted, (start, end) in enumerate(zip(starts, ends, strict=True)):
            if self._closed or (self._limit is not None and emitted >= self._limit):
                return
            readings = tuple(
                Reading(
                    self._sites[i],
                    dict(zip(self.value_columns, self._values[i].tolist(), strict=True)),
                )
                for i in range(start, end)
            )
            yield Tick(pd.Timestamp(self._times[start]).to_pydatetime(), readings)
            if self._delay_s > 0:
                self._sleep(self._delay_s)

    def __iter__(self) -> Iterator[Tick]:
        """Yield ticks in strictly increasing time order until exhausted, limited or closed."""
        return check_order(self._ticks())

    def close(self) -> None:
        """Stop the replay; iteration after this yields nothing."""
        self._closed = True

    def __enter__(self) -> Self:
        """Return the stream itself."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the stream."""
        self.close()
