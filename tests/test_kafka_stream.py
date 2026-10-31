import math
import os
import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from airtwin.config import KafkaConfig, StreamConfig
from airtwin.stream import create_stream
from airtwin.stream.interface import Reading, StreamError, StreamSource, Tick
from airtwin.stream.kafka_stream import (
    KafkaStream,
    Message,
    TickAssembler,
    decode,
    encode,
)
from airtwin.stream.memory_stream import MemoryStream

SETTINGS = KafkaConfig(
    bootstrap_servers=os.environ.get("AIRTWIN_KAFKA_TEST_BOOTSTRAP", "unused:9092"),
    topic_prefix="test",
    spark_master="local[1]",
    spark_driver_memory="512m",
    spark_jars_dir=Path(os.environ.get("AIRTWIN_SPARK_JARS", "/opt/spark-jars")),
    max_offsets_per_trigger=1000,
    poll_timeout_s=0.01,
    idle_timeout_s=0.2,
)


def long_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2013-03-01 00:00", "2013-03-01 00:00", "2013-03-01 01:00", "2013-03-01 02:00"]
            ),
            "site": ["A", "B", "A", "A"],
            "pm25": [1.0, 2.0, np.nan, 4.0],
        }
    )


class FakeTransport:
    """Delivers published records back in batches of a fixed size, reversed inside each batch."""

    def __init__(self, batch_size: int = 2, fail_publish: bool = False) -> None:
        self.batch_size = batch_size
        self.fail_publish = fail_publish
        self.topic = ""
        self.closed = False
        self._records: list[Message] = []

    def open(self, topic: str) -> None:
        self.topic = topic

    def publish(self, records: Sequence[bytes]) -> None:
        if self.fail_publish:
            raise OSError("broker unreachable")
        self._records.extend(decode(r) for r in records)

    def poll(self, timeout_s: float) -> list[Message]:
        batch, self._records = self._records[: self.batch_size], self._records[self.batch_size :]
        return list(reversed(batch))

    def close(self) -> None:
        self.closed = True


def test_encode_decode_round_trip_keeps_nan() -> None:
    tick = Tick(datetime(2013, 3, 1), (Reading("A", {"pm25": math.nan, "no2": 3.0}),))
    message = decode(encode(7, tick, tick.readings[0]))
    assert message == {
        "seq": 7,
        "n": 1,
        "ts": "2013-03-01T00:00:00",
        "site": "A",
        "values": {"pm25": None, "no2": 3.0},
    }
    rebuilt = TickAssembler().add([{**message, "seq": 0}])[0]
    assert math.isnan(rebuilt.reading("A").values["pm25"])


def test_assembler_waits_for_complete_ticks_in_order() -> None:
    def msg(seq: int, site: str, n: int) -> Message:
        return {"seq": seq, "n": n, "ts": f"2013-03-01T0{seq}:00:00", "site": site, "values": {}}

    asm = TickAssembler()
    assert asm.add([msg(1, "A", 1), msg(0, "B", 2)]) == []
    ticks = asm.add([msg(0, "A", 2)])
    assert [t.sites for t in ticks] == [("A", "B"), ("A",)]
    assert asm.emitted == 2
    with pytest.raises(StreamError, match="after it was emitted"):
        asm.add([msg(0, "A", 2)])


def test_kafka_stream_matches_memory_stream() -> None:
    transport = FakeTransport()
    stream = KafkaStream(long_frame(), ["pm25"], settings=SETTINGS, name="t", transport=transport)
    assert isinstance(stream, StreamSource)
    got = list(stream)
    want = list(MemoryStream(long_frame(), ["pm25"]))
    assert [t.timestamp for t in got] == [t.timestamp for t in want]
    assert [t.sites for t in got] == [t.sites for t in want]
    assert got[0].reading("B").values == {"pm25": 2.0}
    assert math.isnan(got[1].reading("A").values["pm25"])
    assert transport.topic.startswith("test-t-")
    assert transport.closed


def test_limit_delay_and_close() -> None:
    pauses: list[float] = []
    stream = KafkaStream(
        long_frame(),
        ["pm25"],
        settings=SETTINGS,
        delay_s=0.1,
        limit=2,
        sleep=pauses.append,
        transport=FakeTransport(batch_size=10),
    )
    assert len(list(stream)) == 2
    assert pauses == [0.1, 0.1]
    with KafkaStream(long_frame(), ["pm25"], settings=SETTINGS, transport=FakeTransport()) as s:
        pass
    assert list(s) == []


def test_publish_failure_and_idle_timeout_raise() -> None:
    failing = KafkaStream(
        long_frame(), ["pm25"], settings=SETTINGS, transport=FakeTransport(fail_publish=True)
    )
    with pytest.raises(StreamError, match=r"(publishing failed|idle timeout)"):
        list(failing)

    class Silent(FakeTransport):
        def publish(self, records: Sequence[bytes]) -> None:
            pass

    silent = KafkaStream(long_frame(), ["pm25"], settings=SETTINGS, transport=Silent())
    with pytest.raises(StreamError, match="idle timeout"):
        list(silent)


def test_slow_consumer_is_not_mistaken_for_idle_kafka() -> None:
    class Gap(FakeTransport):
        """One empty poll after the first batch, as when Spark has not delivered yet."""

        polls = 0

        def poll(self, timeout_s: float) -> list[Message]:
            self.polls += 1
            return [] if self.polls == 2 else super().poll(timeout_s)

    stream = KafkaStream(long_frame(), ["pm25"], settings=SETTINGS, transport=Gap(batch_size=2))
    ticks = []
    for tick in stream:
        ticks.append(tick)
        time.sleep(SETTINGS.idle_timeout_s * 1.5)  # the twin is busy, or paused
    assert len(ticks) == 3


def test_factory_picks_backend_from_settings() -> None:
    base = StreamConfig(backend="memory", replay_delay_s=0.0, uci_site="u", kafka=SETTINGS)
    assert isinstance(create_stream(base, long_frame(), ["pm25"], name="m"), MemoryStream)
    kafka = create_stream(replace(base, backend="kafka"), long_frame(), ["pm25"], name="k")
    assert isinstance(kafka, KafkaStream)


def test_empty_frame_never_opens_a_topic() -> None:
    transport = FakeTransport()
    stream = KafkaStream(long_frame().iloc[0:0], ["pm25"], settings=SETTINGS, transport=transport)
    assert list(stream) == []
    assert transport.topic == ""


@pytest.mark.skipif(
    "AIRTWIN_KAFKA_TEST_BOOTSTRAP" not in os.environ,
    reason="needs a running Kafka broker (set AIRTWIN_KAFKA_TEST_BOOTSTRAP)",
)
def test_real_kafka_and_spark_round_trip() -> None:  # pragma: no cover - runs in the container
    settings = KafkaConfig(**{**SETTINGS.__dict__, "poll_timeout_s": 1.0, "idle_timeout_s": 120})
    got = list(KafkaStream(long_frame(), ["pm25"], settings=settings, name="it"))
    want = list(MemoryStream(long_frame(), ["pm25"]))
    assert [t.timestamp for t in got] == [t.timestamp for t in want]
    assert [t.sites for t in got] == [t.sites for t in want]
