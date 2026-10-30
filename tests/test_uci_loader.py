import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from airtwin.data.uci_loader import (
    REFERENCE_COLUMNS,
    SENSOR_COLUMNS,
    UciFormatError,
    load,
)

HEADER = (
    "Date;Time;CO(GT);PT08.S1(CO);NMHC(GT);C6H6(GT);PT08.S2(NMHC);NOx(GT);PT08.S3(NOx);"
    "NO2(GT);PT08.S4(NO2);PT08.S5(O3);T;RH;AH;;"
)
ROWS = [
    "10/03/2004;18.00.00;2,6;1360;150;11,9;1046;166;1056;113;1692;1268;13,6;48,9;0,7578;;",
    "10/03/2004;19.00.00;-200;1292;112;9,4;955;103;1174;92;1559;972;13,3;47,7;0,7255;;",
    # 20:00 is absent on purpose
    "10/03/2004;21.00.00;2,2;1402;88;9,0;939;131;1140;114;1555;1074;11,9;54,0;0,7502;;",
    ";;;;;;;;;;;;;;;;",
]


def make_archive(tmp_path: Path, lines: list[str], member: str = "AirQualityUCI.csv") -> Path:
    path = tmp_path / "uci.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(member, "\r\n".join([HEADER, *lines]).encode("latin-1"))
    return path


def test_load_parses_decimal_commas_and_missing_tag(tmp_path: Path) -> None:
    frame = load(make_archive(tmp_path, ROWS), missing_value=-200)
    assert frame.index.name == "timestamp"
    assert frame.index[0] == pd.Timestamp("2004-03-10 18:00")
    assert frame.loc["2004-03-10 18:00", "co_ref"] == pytest.approx(2.6)
    assert frame.loc["2004-03-10 18:00", "absolute_humidity"] == pytest.approx(0.7578)
    assert np.isnan(frame.loc["2004-03-10 19:00", "co_ref"])
    assert set(REFERENCE_COLUMNS) | set(SENSOR_COLUMNS) <= set(frame.columns)


def test_load_regularises_to_hourly_and_drops_blank_rows(tmp_path: Path) -> None:
    frame = load(make_archive(tmp_path, ROWS), missing_value=-200)
    assert frame.index.freqstr == "h"
    assert len(frame) == 4
    assert frame.loc["2004-03-10 20:00"].isna().all()
    assert (frame.dtypes == "float64").all()


def test_duplicate_timestamp_raises(tmp_path: Path) -> None:
    with pytest.raises(UciFormatError, match="duplicate"):
        load(make_archive(tmp_path, [ROWS[0], ROWS[0]]), missing_value=-200)


def test_wrong_member_or_columns_raise(tmp_path: Path) -> None:
    with pytest.raises(UciFormatError, match="no member"):
        load(make_archive(tmp_path, ROWS, member="other.csv"), missing_value=-200)
    bad = tmp_path / "bad"
    bad.mkdir()
    path = bad / "uci.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("AirQualityUCI.csv", "Date;Time;T\n10/03/2004;18.00.00;1,0\n")
    with pytest.raises(UciFormatError, match="lacks columns"):
        load(path, missing_value=-200)
