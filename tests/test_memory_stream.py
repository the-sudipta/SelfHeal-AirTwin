import math
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from airtwin.stream.interface import StreamError, StreamSource
from airtwin.stream.memory_stream import MemoryStream


def long_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2013-03-01 01:00", "2013-03-01 00:00", "2013-03-01 00:00", "2013-03-01 02:00"]
            ),
            "site": ["B", "B", "A", "A"],
            "pm25": [3.0, 2.0, 1.0, np.nan],
            "no2": [30.0, 20.0, 10.0, 40.0],
        }
    )


def test_satisfies_protocol() -> None:
    assert isinstance(MemoryStream(long_frame(), ["pm25"]), StreamSource)


def test_groups_rows_into_sorted_ticks() -> None:
    ticks = list(MemoryStream(long_frame(), ["pm25", "no2"]))
    assert [t.timestamp for t in ticks] == [
        datetime(2013, 3, 1, 0),
        datetime(2013, 3, 1, 1),
        datetime(2013, 3, 1, 2),
    ]
    assert ticks[0].sites == ("A", "B")
    assert ticks[0].reading("B").values == {"pm25": 2.0, "no2": 20.0}
    assert ticks[1].sites == ("B",)
    assert math.isnan(ticks[2].reading("A").values["pm25"])


def test_limit_delay_and_close() -> None:
    pauses: list[float] = []
    stream = MemoryStream(long_frame(), ["pm25"], delay_s=0.5, limit=2, sleep=pauses.append)
    assert len(list(stream)) == 2
    assert pauses == [0.5, 0.5]
    with MemoryStream(long_frame(), ["pm25"]) as live:
        first = next(iter(live))
        assert first.sites == ("A", "B")
    assert list(live) == []


def test_from_wide_builds_single_site_stream() -> None:
    wide = pd.DataFrame(
        {"co_ref": [2.6, np.nan]},
        index=pd.DatetimeIndex(
            pd.to_datetime(["2004-03-10 18:00", "2004-03-10 19:00"]), name="timestamp"
        ),
    )
    ticks = list(MemoryStream.from_wide(wide, "uci_city", ["co_ref"], name="uci"))
    assert [t.sites for t in ticks] == [("uci_city",), ("uci_city",)]
    assert ticks[0].reading("uci_city").values["co_ref"] == 2.6


def test_empty_frame_yields_nothing() -> None:
    assert list(MemoryStream(long_frame().iloc[0:0], ["pm25"])) == []


def test_invalid_input_raises() -> None:
    with pytest.raises(StreamError, match="lacks columns"):
        MemoryStream(long_frame(), ["o3"])
    with pytest.raises(StreamError, match="more than once"):
        MemoryStream(pd.concat([long_frame(), long_frame()]), ["pm25"])
    with pytest.raises(StreamError, match="must not be negative"):
        MemoryStream(long_frame(), ["pm25"], delay_s=-1)
