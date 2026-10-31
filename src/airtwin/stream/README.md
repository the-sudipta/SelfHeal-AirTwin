# `airtwin.stream`

Turns a cleaned hourly table into a live feed: one tick per hour, each holding every site's reading, so the twin sees data exactly as it would arrive from the city.

| File | What it does |
|---|---|
| `interface.py` | The contract every backend follows: `Reading` (one site, one hour, frozen values with NaN for missing), `Tick` (one hour, readings sorted by unique site), the `StreamSource` protocol (iterable, closable context manager) and `check_order` (time must strictly increase) |
| `__init__.py` | `create_stream` opens the backend named in the configuration; both return the same `StreamSource` |
| `memory_stream.py` | `MemoryStream`, the default backend: replays a long table (`timestamp`, `site`, value columns) in memory with optional pause between ticks and a tick limit; `from_wide` adapts single-site tables such as UCI Air Quality |
| `kafka_stream.py` | `KafkaStream`: a producer thread publishes every reading as JSON to a fresh Kafka topic; Spark Structured Streaming (local mode) reads the topic in micro-batches; `TickAssembler` rebuilds complete hourly ticks in order, so the twin sees the same ticks as from memory |

## How it connects

- Input comes from the loaders in `airtwin.data`; the backend and replay pause come from the `stream` section of `configs/default.yaml`.
- The twin engine (later milestone) consumes any `StreamSource`, so it never knows which backend is running.
- Both backends implement the same protocol, which makes them interchangeable; `--backend kafka` switches without code changes.
- The Kafka backend needs a broker (the `kafka` service in `docker-compose.yml`) and the connector JARs baked into the image under `/opt/spark-jars`.
- `airtwin replay` runs a backend over a full dataset and reports ticks, readings and readings per second.
