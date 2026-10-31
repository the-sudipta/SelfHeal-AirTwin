"""Kafka + Spark Structured Streaming backend.

A producer thread publishes every reading as one JSON record to a fresh Kafka topic
(physical -> virtual). Spark reads the topic as a structured stream, parses the records
in micro-batches, and hands them back; a :class:`TickAssembler` rebuilds complete hourly
ticks in their original order, so consumers see exactly the same ticks as from the
memory backend.
"""

from __future__ import annotations

import json
import math
import queue
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, Sequence
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, Self

import pandas as pd

from airtwin.config import KafkaConfig
from airtwin.stream.interface import Reading, StreamError, Tick, check_order
from airtwin.stream.memory_stream import MemoryStream

Message = dict[str, Any]


def encode(seq: int, tick: Tick, reading: Reading) -> bytes:
    """Serialise one reading of one tick as a JSON record (NaN becomes null)."""
    values = {k: (None if math.isnan(v) else v) for k, v in reading.values.items()}
    record = {
        "seq": seq,
        "n": len(tick.readings),
        "ts": tick.timestamp.isoformat(),
        "site": reading.site,
        "values": values,
    }
    return json.dumps(record, separators=(",", ":")).encode()


def decode(raw: bytes) -> Message:
    """Parse a JSON record produced by :func:`encode`."""
    message: Message = json.loads(raw)
    return message


class TickAssembler:
    """Rebuild ticks from records that may arrive split across or mixed within batches."""

    def __init__(self) -> None:
        """Start expecting tick number 0."""
        self._next = 0
        self._pending: dict[int, dict[str, Message]] = {}

    @property
    def emitted(self) -> int:
        """Number of complete ticks handed out so far."""
        return self._next

    def add(self, messages: Iterable[Message]) -> list[Tick]:
        """Add records and return every tick that is now complete, in sequence order.

        Raises:
            StreamError: If a record belongs to a tick that was already emitted.
        """
        for message in messages:
            seq = int(message["seq"])
            if seq < self._next:
                raise StreamError(f"record for tick {seq} arrived after it was emitted")
            self._pending.setdefault(seq, {})[str(message["site"])] = message
        ready: list[Tick] = []
        while self._next in self._pending:
            parts = self._pending[self._next]
            if len(parts) < int(next(iter(parts.values()))["n"]):
                break
            del self._pending[self._next]
            ready.append(_to_tick(parts))
            self._next += 1
        return ready


def _to_tick(parts: dict[str, Message]) -> Tick:
    """Turn all records of one tick into a :class:`Tick` with NaN for null values."""
    readings = tuple(
        Reading(site, {k: (math.nan if v is None else float(v)) for k, v in m["values"].items()})
        for site, m in sorted(parts.items())
    )
    first = next(iter(parts.values()))
    return Tick(datetime.fromisoformat(str(first["ts"])), readings)


class Transport(Protocol):
    """Where records go and where parsed micro-batches come back from."""

    def open(self, topic: str) -> None:
        """Create the topic and start consuming it."""
        ...

    def publish(self, records: Sequence[bytes]) -> None:
        """Send the records of one tick and make sure they are delivered."""
        ...

    def poll(self, timeout_s: float) -> list[Message]:
        """Return the next parsed micro-batch, or an empty list if none arrived in time."""
        ...

    def close(self) -> None:
        """Stop consuming and remove the topic."""
        ...


class KafkaSparkTransport:
    """Real transport: confluent-kafka producer and a Spark Structured Streaming consumer."""

    def __init__(self, settings: KafkaConfig) -> None:
        """Keep the settings; nothing connects until :meth:`open`."""
        self._settings = settings
        self._batches: queue.Queue[list[Message]] = queue.Queue()
        self._topic = ""
        self._producer: Any = None
        self._query: Any = None
        self._checkpoint: tempfile.TemporaryDirectory[str] | None = None

    def _spark(self) -> Any:
        """Return a local Spark session that can read Kafka."""
        from pyspark.sql import SparkSession

        jars = sorted(str(p) for p in Path(self._settings.spark_jars_dir).glob("*.jar"))
        if not jars:
            raise StreamError(f"no Spark-Kafka connector JARs in {self._settings.spark_jars_dir}")
        return (
            SparkSession.builder.master(self._settings.spark_master)
            .appName("selfheal-airtwin")
            .config("spark.jars", ",".join(jars))
            .config("spark.driver.memory", self._settings.spark_driver_memory)
            .config("spark.sql.shuffle.partitions", "1")
            .config("spark.ui.enabled", "false")
            .getOrCreate()
        )

    def open(self, topic: str) -> None:
        """Create a one-partition topic, then start the Spark query that consumes it."""
        from confluent_kafka import Producer
        from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore[attr-defined]
        from pyspark.sql import functions as sf
        from pyspark.sql import types as st

        servers = self._settings.bootstrap_servers
        # The admin client must stay referenced until the creation future resolves.
        admin = AdminClient({"bootstrap.servers": servers})
        futures = admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])
        futures[topic].result(timeout=self._settings.idle_timeout_s)
        self._topic = topic
        self._producer = Producer({"bootstrap.servers": servers, "linger.ms": 5})

        schema = st.StructType(
            [
                st.StructField("seq", st.LongType()),
                st.StructField("n", st.IntegerType()),
                st.StructField("ts", st.StringType()),
                st.StructField("site", st.StringType()),
                st.StructField("values", st.MapType(st.StringType(), st.DoubleType())),
            ]
        )
        source = (
            self._spark()
            .readStream.format("kafka")
            .option("kafka.bootstrap.servers", servers)
            .option("subscribe", topic)
            .option("startingOffsets", "earliest")
            .option("maxOffsetsPerTrigger", self._settings.max_offsets_per_trigger)
            .load()
        )
        parsed = source.select(sf.from_json(sf.col("value").cast("string"), schema).alias("m"))
        self._checkpoint = tempfile.TemporaryDirectory(prefix="airtwin-checkpoint-")

        def collect(batch: Any, _batch_id: int) -> None:
            rows = [row.m.asDict(recursive=True) for row in batch.collect()]
            if rows:
                self._batches.put(rows)

        self._query = (
            parsed.writeStream.foreachBatch(collect)
            .option("checkpointLocation", self._checkpoint.name)
            .start()
        )

    def publish(self, records: Sequence[bytes]) -> None:
        """Produce the records and wait until Kafka has acknowledged them."""
        for record in records:
            self._producer.produce(self._topic, record)
        remaining = self._producer.flush(self._settings.idle_timeout_s)
        if remaining:
            raise StreamError(f"{remaining} records were not delivered to Kafka")

    def poll(self, timeout_s: float) -> list[Message]:
        """Return the next micro-batch, raising if the Spark query has failed."""
        if self._query is not None and self._query.exception() is not None:
            raise StreamError(f"Spark query failed: {self._query.exception()}")
        try:
            return self._batches.get(timeout=timeout_s)
        except queue.Empty:
            return []

    def close(self) -> None:
        """Stop the query, flush the producer and delete the topic."""
        if self._query is not None:
            self._query.stop()
            self._query = None
        if self._producer is not None:
            self._producer.flush(self._settings.poll_timeout_s)
            self._producer = None
        if self._topic:
            from confluent_kafka.admin import AdminClient

            admin = AdminClient({"bootstrap.servers": self._settings.bootstrap_servers})
            admin.delete_topics([self._topic])[self._topic].result(
                timeout=self._settings.idle_timeout_s
            )
            self._topic = ""
        if self._checkpoint is not None:
            self._checkpoint.cleanup()
            self._checkpoint = None


class KafkaStream:
    """Replay a long table through Kafka and Spark; same constructor shape as the memory backend."""

    def __init__(
        self,
        frame: pd.DataFrame,
        value_columns: Sequence[str],
        *,
        settings: KafkaConfig,
        name: str = "kafka",
        delay_s: float = 0.0,
        limit: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
        transport: Transport | None = None,
    ) -> None:
        """Prepare the replay.

        Args:
            frame: Long table with ``timestamp`` and ``site`` columns plus the value columns.
            value_columns: Columns copied into each reading.
            settings: Kafka and Spark settings from the configuration.
            name: Name of this source; also part of the topic name.
            delay_s: Pause after publishing each tick.
            limit: Stop after this many ticks; ``None`` replays everything.
            sleep: Function used to pause; replaced in tests.
            transport: Message transport; defaults to :class:`KafkaSparkTransport`.
        """
        self.name = name
        self._source = MemoryStream(frame, value_columns, name=name, limit=limit)
        self._settings = settings
        self._delay_s = delay_s
        self._sleep = sleep
        self._transport = transport or KafkaSparkTransport(settings)
        self._closed = False

    def _publish_all(self, errors: list[BaseException]) -> None:
        """Publish every tick in order; runs in the producer thread."""
        try:
            for seq, tick in enumerate(self._source):
                if self._closed:
                    return
                self._transport.publish([encode(seq, tick, r) for r in tick.readings])
                if self._delay_s > 0:
                    self._sleep(self._delay_s)
        except BaseException as exc:  # handed to the consuming thread
            errors.append(exc)

    def _ticks(self) -> Iterator[Tick]:
        """Publish in a background thread and yield ticks as Spark delivers them."""
        total = self._source.n_ticks
        if total == 0 or self._closed:
            return
        topic = f"{self._settings.topic_prefix}-{self.name}-{uuid.uuid4().hex[:8]}"
        self._transport.open(topic)
        errors: list[BaseException] = []
        producer = threading.Thread(target=self._publish_all, args=(errors,), daemon=True)
        producer.start()
        assembler = TickAssembler()
        last_progress = time.monotonic()
        try:
            while assembler.emitted < total and not self._closed:
                if errors:
                    raise StreamError(f"publishing failed: {errors[0]}") from errors[0]
                batch = self._transport.poll(self._settings.poll_timeout_s)
                if batch:
                    last_progress = time.monotonic()
                elif time.monotonic() - last_progress > self._settings.idle_timeout_s:
                    raise StreamError("no data arrived from Kafka within the idle timeout")
                yield from assembler.add(batch)
        finally:
            self._closed = True
            producer.join(self._settings.idle_timeout_s)
            self._transport.close()

    def __iter__(self) -> Iterator[Tick]:
        """Yield ticks in strictly increasing time order until exhausted, limited or closed."""
        return check_order(self._ticks())

    def close(self) -> None:
        """Stop publishing and consuming; iteration after this yields nothing."""
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
