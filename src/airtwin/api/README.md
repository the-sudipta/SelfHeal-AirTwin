# `airtwin.api`

The live twin over HTTP: it runs the twin engine on a replayed dataset and serves its state, an event stream and commands to the web twin.

| File | What it does |
|---|---|
| `events.py` | `TwinService`: a background thread loads the dataset, replays it through the engine at full speed past the calibration year and the drift baseline, then one hourly tick per `api.tick_seconds`; after each tick it keeps a frame (raw, expected, corrected, original value, drift score, status, correction per sensor), the twin's events and the network RMSE of raw and published values against the original data; commands pause or resume, inject a labelled demonstration drift, and mark a sensor recalibrated (which also removes its injected drift) |
| `routes.py` | REST under `/api`: `health`, `status`, `state`, `history`, `maintenance`, `events`, `what-if/{sensor}`, `control`, `sensors/{sensor}/inject`, `sensors/{sensor}/recalibrate`; and `stream`, Server-Sent Events with one `tick` message per change, resumable through `Last-Event-ID` |
| `app.py` | `create_app()`: the FastAPI app with the service started and stopped by the server's lifespan, the web twin from `web/` mounted at `/`, and OpenAPI docs at `/api/docs`; `open_live_run()` verifies and loads the dataset and builds the engine and the configured stream backend |

## How it connects

- `airtwin serve` (the container's default command) runs `create_app()` with Uvicorn on port 8080; with `--backend kafka` the same twin reads from Kafka + Spark.
- The service talks to `twin/engine.py` only, never to the twin's parts; sensors are named `site:variable`, e.g. `Dongsi:pm25`.
- Every setting (dataset, twinned variables, fast-forward length, tick rate, history and event-log sizes, the injected drift) is in the `api` section of `configs/default.yaml`.
- The web twin in `web/` is the client of these endpoints; `tests/test_api.py` drives the service and the HTTP API on a small synthetic city.
