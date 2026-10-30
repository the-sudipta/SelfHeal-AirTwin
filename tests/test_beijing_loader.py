import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from airtwin.data.beijing_loader import BeijingFormatError, load, stations

HEADER = (
    '"No","year","month","day","hour","PM2.5","PM10","SO2","NO2","CO","O3",'
    '"TEMP","PRES","DEWP","RAIN","wd","WSPM","station"'
)


def station_csv(name: str, rows: list[str]) -> str:
    return "\n".join([HEADER, *[f"{i + 1},{r},{name}" for i, r in enumerate(rows)]]) + "\n"


def make_archive(tmp_path: Path, files: dict[str, str], extra: bool = True) -> Path:
    inner_buf = io.BytesIO()
    with zipfile.ZipFile(inner_buf, "w") as inner:
        inner.writestr("PRSA_Data_20130301-20170228/", "")
        for name, text in files.items():
            inner.writestr(f"PRSA_Data_20130301-20170228/PRSA_Data_{name}_x.csv", text)
    path = tmp_path / "beijing.zip"
    with zipfile.ZipFile(path, "w") as outer:
        outer.writestr("PRSA2017_Data_20130301-20170228.zip", inner_buf.getvalue())
        if extra:
            outer.writestr("data.csv", "Date,Open\n2018-07-02,1\n")
    return path


A_ROWS = [
    '2013,3,1,1,8,8,4,7,300,77,-1.1,1023,-18.2,0,"N",4.7',
    '2013,3,1,0,4,4,4,7,300,77,-0.7,1023,-18.8,0,"NNW",4.4',
]
B_ROWS = ["2013,3,1,0,NA,6,NA,11,400,70,-0.5,1024,-19.0,0,NA,2.0"]


def test_load_combines_stations_and_ignores_unrelated_files(tmp_path: Path) -> None:
    archive = make_archive(
        tmp_path, {"Alpha": station_csv("Alpha", A_ROWS), "Beta": station_csv("Beta", B_ROWS)}
    )
    frame = load(archive, missing_token="NA")
    assert stations(frame) == ["Alpha", "Beta"]
    assert len(frame) == 3
    assert list(frame.columns[:2]) == ["timestamp", "station"]


def test_load_builds_sorted_timestamps(tmp_path: Path) -> None:
    frame = load(make_archive(tmp_path, {"Alpha": station_csv("Alpha", A_ROWS)}), "NA")
    assert frame["timestamp"].tolist() == [
        pd.Timestamp("2013-03-01 00:00"),
        pd.Timestamp("2013-03-01 01:00"),
    ]
    assert frame.loc[0, "pm25"] == 4.0
    assert frame.loc[0, "wind_direction"] == "NNW"


def test_missing_token_becomes_nan(tmp_path: Path) -> None:
    frame = load(make_archive(tmp_path, {"Beta": station_csv("Beta", B_ROWS)}), "NA")
    assert np.isnan(frame.loc[0, "pm25"])
    assert np.isnan(frame.loc[0, "so2"])
    assert pd.isna(frame.loc[0, "wind_direction"])
    assert frame["pm10"].dtype == "float64"


def test_duplicate_timestamp_raises(tmp_path: Path) -> None:
    archive = make_archive(tmp_path, {"Alpha": station_csv("Alpha", [A_ROWS[0], A_ROWS[0]])})
    with pytest.raises(BeijingFormatError, match="duplicate"):
        load(archive, "NA")


def test_layout_errors_raise(tmp_path: Path) -> None:
    with pytest.raises(BeijingFormatError, match="no station files"):
        load(make_archive(tmp_path, {}), "NA")
    other = tmp_path / "other"
    other.mkdir()
    path = other / "x.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("data.csv", "a\n")
    with pytest.raises(BeijingFormatError, match="exactly one"):
        load(path, "NA")
    bad = tmp_path / "bad"
    bad.mkdir()
    archive = make_archive(bad, {"Alpha": '"year","month","day","hour","station"\n2013,3,1,0,A\n'})
    with pytest.raises(BeijingFormatError, match="lacks columns"):
        load(archive, "NA")
