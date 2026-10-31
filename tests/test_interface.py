import math
from datetime import datetime, timedelta

import pytest

from airtwin.stream.interface import Reading, StreamError, Tick, check_order

T0 = datetime(2013, 3, 1)


def tick(hour: int, *sites: str) -> Tick:
    return Tick(T0 + timedelta(hours=hour), tuple(Reading(s, {"pm25": 1.0}) for s in sites))


def test_reading_is_frozen_and_reports_observed_values() -> None:
    source = {"pm25": 4.0, "no2": math.nan}
    reading = Reading("Dongsi", source)
    source["pm25"] = 99.0
    assert reading.values["pm25"] == 4.0
    assert reading.observed() == {"pm25": 4.0}
    with pytest.raises(TypeError):
        reading.values["pm25"] = 1.0  # type: ignore[index]


def test_tick_requires_unique_sorted_sites() -> None:
    assert tick(0, "A", "B").sites == ("A", "B")
    with pytest.raises(StreamError, match="unique and sorted"):
        tick(0, "B", "A")
    with pytest.raises(StreamError, match="unique and sorted"):
        tick(0, "A", "A")


def test_tick_reading_lookup() -> None:
    t = tick(0, "A", "B")
    assert t.reading("B").site == "B"
    with pytest.raises(KeyError):
        t.reading("C")


def test_check_order_accepts_increasing_and_rejects_repeats() -> None:
    ok = [tick(0, "A"), tick(1, "A"), tick(5, "A")]
    assert list(check_order(iter(ok))) == ok
    with pytest.raises(StreamError, match="not after"):
        list(check_order(iter([tick(1, "A"), tick(1, "A")])))
