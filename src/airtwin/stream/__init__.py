"""Streaming backends that replay hourly sensor data as a live feed."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from airtwin.config import StreamConfig
from airtwin.stream.interface import StreamSource
from airtwin.stream.kafka_stream import KafkaStream
from airtwin.stream.memory_stream import MemoryStream


def create_stream(
    settings: StreamConfig,
    frame: pd.DataFrame,
    value_columns: Sequence[str],
    *,
    name: str,
    limit: int | None = None,
) -> StreamSource:
    """Open the backend named in ``settings`` over a long table; both share one contract."""
    if settings.backend == "kafka":
        return KafkaStream(
            frame,
            value_columns,
            settings=settings.kafka,
            name=name,
            delay_s=settings.replay_delay_s,
            limit=limit,
        )
    return MemoryStream(
        frame, value_columns, name=name, delay_s=settings.replay_delay_s, limit=limit
    )
