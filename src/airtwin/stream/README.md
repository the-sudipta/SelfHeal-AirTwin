# `airtwin.stream`

Turns a cleaned hourly table into a live feed: one tick per hour, each holding every site's reading, so the twin sees data exactly as it would arrive from the city.

| File | What it does |
|---|---|
| `interface.py` | The contract every backend follows: `Reading` (one site, one hour, frozen values with NaN for missing), `Tick` (one hour, readings sorted by unique site), the `StreamSource` protocol (iterable, closable context manager) and `check_order` (time must strictly increase) |
| `memory_stream.py` | `MemoryStream`, the default backend: replays a long table (`timestamp`, `site`, value columns) in memory with optional pause between ticks and a tick limit; `from_wide` adapts single-site tables such as UCI Air Quality |

## How it connects

- Input comes from the loaders in `airtwin.data`; the backend and replay pause come from the `stream` section of `configs/default.yaml`.
- The twin engine (later milestone) consumes any `StreamSource`, so it never knows which backend is running.
- The Kafka + Spark backend (`kafka_stream.py`, next milestone) implements the same protocol, which makes the two backends interchangeable.
- `airtwin replay` runs a backend over a full dataset and reports ticks, readings and readings per second.
