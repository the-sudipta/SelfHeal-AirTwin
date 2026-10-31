"""The two datasets by name, loaded as the long table every stream backend replays."""

from __future__ import annotations

import pandas as pd

from airtwin.config import Config
from airtwin.data import beijing_loader, uci_loader
from airtwin.stream.memory_stream import SITE, wide_to_long

UCI_KEY = "uci_air_quality"
BEIJING_KEY = "beijing_multisite"


def load_long(cfg: Config, dataset: str) -> tuple[pd.DataFrame, list[str]]:
    """Load one downloaded dataset as a long table and name its numeric columns."""
    data = cfg.data
    archive = data.raw_dir / data.dataset(dataset).archive
    if dataset == UCI_KEY:
        frame = wide_to_long(uci_loader.load(archive, data.uci_missing_value), cfg.stream.uci_site)
        columns = [
            *uci_loader.SENSOR_COLUMNS,
            *uci_loader.REFERENCE_COLUMNS,
            *uci_loader.WEATHER_COLUMNS,
        ]
    else:
        frame = beijing_loader.load(archive, data.beijing_missing_token).rename(
            columns={"station": SITE}
        )
        columns = [*beijing_loader.POLLUTANT_COLUMNS, *beijing_loader.WEATHER_COLUMNS]
    return frame, columns
