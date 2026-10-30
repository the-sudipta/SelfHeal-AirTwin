"""Load and clean the UCI Air Quality dataset (id 360) straight from its archive."""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

MEMBER = "AirQualityUCI.csv"
TIMESTAMP_FORMAT = "%d/%m/%Y %H.%M.%S"

# Original column -> clean name. GT columns come from the certified reference analyzer,
# PT08 columns are the low-cost metal-oxide sensor responses.
COLUMNS = {
    "CO(GT)": "co_ref",
    "PT08.S1(CO)": "s1_co",
    "NMHC(GT)": "nmhc_ref",
    "C6H6(GT)": "c6h6_ref",
    "PT08.S2(NMHC)": "s2_nmhc",
    "NOx(GT)": "nox_ref",
    "PT08.S3(NOx)": "s3_nox",
    "NO2(GT)": "no2_ref",
    "PT08.S4(NO2)": "s4_no2",
    "PT08.S5(O3)": "s5_o3",
    "T": "temperature",
    "RH": "relative_humidity",
    "AH": "absolute_humidity",
}
REFERENCE_COLUMNS = ("co_ref", "nmhc_ref", "c6h6_ref", "nox_ref", "no2_ref")
SENSOR_COLUMNS = ("s1_co", "s2_nmhc", "s3_nox", "s4_no2", "s5_o3")
WEATHER_COLUMNS = ("temperature", "relative_humidity", "absolute_humidity")


class UciFormatError(ValueError):
    """Raised when the archive does not have the expected layout."""


def read_raw(archive: Path) -> pd.DataFrame:
    """Read the original semicolon-separated CSV from the archive without changing values."""
    with zipfile.ZipFile(archive) as zf:
        if MEMBER not in zf.namelist():
            raise UciFormatError(f"{archive.name} has no member {MEMBER}")
        with zf.open(MEMBER) as handle:
            frame = pd.read_csv(handle, sep=";", decimal=",", encoding="latin-1")
    missing = set(COLUMNS) - set(frame.columns)
    if missing or not {"Date", "Time"} <= set(frame.columns):
        raise UciFormatError(f"{archive.name} lacks columns {sorted(missing)}")
    return frame


def clean(raw: pd.DataFrame, missing_value: float) -> pd.DataFrame:
    """Turn the original table into a regular hourly frame.

    - Drops the empty trailing columns and the blank rows at the end of the file.
    - Builds a ``timestamp`` index from ``Date`` and ``Time``.
    - Replaces the ``missing_value`` tag with NaN.
    - Renames columns to the names in :data:`COLUMNS`.
    - Reindexes to a complete hourly range, so absent hours appear as NaN rows.

    Raises:
        UciFormatError: If a timestamp occurs twice.
    """
    rows = raw.dropna(subset=["Date", "Time"])
    timestamps = pd.to_datetime(rows["Date"] + " " + rows["Time"], format=TIMESTAMP_FORMAT)
    frame = rows[list(COLUMNS)].rename(columns=COLUMNS).astype("float64")
    frame.index = pd.DatetimeIndex(timestamps, name="timestamp")
    if frame.index.has_duplicates:
        raise UciFormatError("duplicate timestamps in UCI Air Quality data")
    frame = frame.replace(missing_value, np.nan).sort_index()
    return frame.asfreq("h")


def load(archive: Path, missing_value: float) -> pd.DataFrame:
    """Read and clean the UCI Air Quality archive in one step."""
    return clean(read_raw(archive), missing_value)
