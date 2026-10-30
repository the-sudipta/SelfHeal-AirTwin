"""Load and clean the UCI Beijing Multi-Site Air Quality dataset (id 501) from its archive."""

from __future__ import annotations

import fnmatch
import io
import zipfile
from pathlib import Path

import pandas as pd

INNER_ARCHIVE = "PRSA2017_Data_*.zip"
STATION_FILE = "*PRSA_Data_*.csv"
TIME_PARTS = ["year", "month", "day", "hour"]

# Original column -> clean name. Pollutants in ug/m3; CO in ug/m3 as published.
COLUMNS = {
    "station": "station",
    "PM2.5": "pm25",
    "PM10": "pm10",
    "SO2": "so2",
    "NO2": "no2",
    "CO": "co",
    "O3": "o3",
    "TEMP": "temperature",
    "PRES": "pressure",
    "DEWP": "dew_point",
    "RAIN": "rain",
    "wd": "wind_direction",
    "WSPM": "wind_speed",
}
POLLUTANT_COLUMNS = ("pm25", "pm10", "so2", "no2", "co", "o3")
WEATHER_COLUMNS = ("temperature", "pressure", "dew_point", "rain", "wind_speed")


class BeijingFormatError(ValueError):
    """Raised when the archive does not have the expected layout."""


def _station_tables(archive: Path, missing_token: str) -> list[pd.DataFrame]:
    """Read every per-station CSV from the inner archive, ignoring unrelated files."""
    with zipfile.ZipFile(archive) as outer:
        inner_names = fnmatch.filter(outer.namelist(), INNER_ARCHIVE)
        if len(inner_names) != 1:
            raise BeijingFormatError(f"{archive.name} must hold exactly one {INNER_ARCHIVE}")
        inner_bytes = outer.read(inner_names[0])
    tables = []
    with zipfile.ZipFile(io.BytesIO(inner_bytes)) as inner:
        for name in sorted(fnmatch.filter(inner.namelist(), STATION_FILE)):
            with inner.open(name) as handle:
                tables.append(pd.read_csv(handle, na_values=[missing_token], keep_default_na=False))
    if not tables:
        raise BeijingFormatError(f"{archive.name} contains no station files")
    return tables


def clean(table: pd.DataFrame) -> pd.DataFrame:
    """Clean one station table: build ``timestamp``, rename columns, sort by time.

    Raises:
        BeijingFormatError: If columns are missing or a timestamp occurs twice.
    """
    missing = (set(COLUMNS) | set(TIME_PARTS)) - set(table.columns)
    if missing:
        raise BeijingFormatError(f"station table lacks columns {sorted(missing)}")
    frame = table[list(COLUMNS)].rename(columns=COLUMNS)
    frame.insert(0, "timestamp", pd.to_datetime(table[TIME_PARTS]))
    numeric = [c for c in frame.columns if c not in ("timestamp", "station", "wind_direction")]
    frame[numeric] = frame[numeric].astype("float64")
    if frame["timestamp"].duplicated().any():
        raise BeijingFormatError(f"duplicate timestamps for station {frame['station'].iloc[0]}")
    return frame.sort_values("timestamp", ignore_index=True)


def load(archive: Path, missing_token: str) -> pd.DataFrame:
    """Read all stations into one long table sorted by station and time."""
    frames = [clean(table) for table in _station_tables(archive, missing_token)]
    combined = pd.concat(frames, ignore_index=True)
    return combined.sort_values(["station", "timestamp"], ignore_index=True)


def stations(frame: pd.DataFrame) -> list[str]:
    """Return the station names in alphabetical order."""
    return sorted(frame["station"].unique().tolist())
