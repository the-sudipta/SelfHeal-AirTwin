import json
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from types import TracebackType

import pytest
from fastapi.testclient import TestClient

from airtwin.api.app import create_app
from airtwin.api.events import INJECT, Phase, TwinService
from airtwin.config import ApiConfig, InjectSettings, load_config
from airtwin.stream.interface import StreamSource, Tick
from airtwin.twin.engine import TwinEngine
from test_engine import BASE, CAL, SITES, TARGET, TWIN, ticks

REPO = Path(__file__).resolve().parents[1]
FAST = CAL + BASE + 50
LIVE = 400
SENSOR = "C:pm25"
SETTINGS = ApiConfig(
    host="127.0.0.1",
    port=8080,
    dataset="demo",
    variables=("pm25",),
    fast_forward_hours=FAST,
    tick_seconds=0.0,
    history_hours=48,
    event_log=50,
    rmse_window_hours=24,
    poll_s=0.01,
    keepalive_s=0.05,
    max_what_if_days=30,
    web_dir=REPO / "no-web",
    inject=InjectSettings(kind="step", magnitude=0.4, ramp_hours=24, exp_rate=4.0),
)


class Ticks:
    """A stream over a prepared list of ticks."""

    name = "test"

    def __init__(self, items: list[Tick]) -> None:
        self._items = items

    def __iter__(self) -> Iterator[Tick]:
        return iter(self._items)

    def close(self) -> None:
        self._items = []

    def __enter__(self) -> "Ticks":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def open_run() -> tuple[TwinEngine, StreamSource]:
    """The engine-test city without its built-in drift."""
    return TwinEngine(TWIN, TARGET, SITES), Ticks(ticks(FAST + LIVE, gain=1.0))


def wait(condition: Callable[[], bool], timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


@pytest.fixture(scope="module")
def finished() -> TwinService:
    """A run paused at the first live hour, given a drift on C, then run to the end."""
    service = TwinService(SETTINGS, open_run)
    service.set_running(False)
    service.start()
    wait(lambda: service.phase is Phase.RUNNING)
    assert service.status()["hour"] == FAST
    event = service.inject(SENSOR)
    assert event["kind"] == INJECT and event["sensor"] == SENSOR
    service.set_running(True)
    service.join(120)
    assert service.phase is Phase.FINISHED, service.error
    return service


def test_fast_forward_then_pause_holds_the_run() -> None:
    service = TwinService(SETTINGS, open_run)
    service.set_running(False)
    service.start()
    wait(lambda: service.phase is Phase.RUNNING)
    hour = service.status()["hour"]
    time.sleep(0.2)
    assert service.status()["hour"] == hour == FAST
    assert len(service.history()) == SETTINGS.history_hours
    service.stop()


def test_injected_drift_is_detected_healed_and_ranked(finished: TwinService) -> None:
    kinds = [(e["kind"], e["sensor"]) for e in finished.events()]
    assert ("detect", SENSOR) in kinds and ("heal", SENSOR) in kinds
    frame = finished.state()["frame"]
    c = next(s for s in frame["sensors"] if s["site"] == "C")
    assert c["injected"] is True
    assert c["raw"] == pytest.approx(c["truth"] * 1.4, rel=1e-3)
    assert abs(c["corrected"] - c["truth"]) < abs(c["raw"] - c["truth"])
    network = finished.network()
    assert network["window_hours"] == SETTINGS.rmse_window_hours
    assert network["rmse_published"] < network["rmse_raw"]
    assert finished.maintenance()[0]["sensor"] == SENSOR
    assert finished.status()["readings"] == (FAST + LIVE) * len(SITES)


def test_events_are_numbered_and_filtered(finished: TwinService) -> None:
    events = finished.events()
    ids = [e["id"] for e in events]
    assert ids == sorted(ids, reverse=True)
    assert "watch" not in {e["kind"] for e in events}
    assert finished.events(ids[0]) == []
    assert finished.update(ids[1])["events"] == events[:1]


def test_what_if_and_unknown_sensors(finished: TwinService) -> None:
    result = finished.what_if(SENSOR, [7, 3, 7])
    assert [p["days"] for p in result["projections"]] == [3, 7]
    assert result["points_used"] >= 1
    for bad in ("Z:pm25", "nonsense"):
        with pytest.raises(KeyError):
            finished.what_if(bad, [7])


def test_failure_is_reported() -> None:
    def broken() -> tuple[TwinEngine, StreamSource]:
        raise OSError("disk gone")

    service = TwinService(SETTINGS, broken)
    service.start()
    service.join(10)
    assert service.phase is Phase.FAILED
    assert service.status()["error"] == "OSError: disk gone"


def test_http_api(finished: TwinService, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>twin</h1>", encoding="utf-8")
    cfg = replace(
        load_config(REPO / "configs" / "default.yaml"), api=replace(SETTINGS, web_dir=tmp_path)
    )
    with TestClient(create_app(cfg, finished)) as client:
        assert client.get("/").text == "<h1>twin</h1>"
        assert client.get("/api/health").json()["phase"] == "finished"
        assert client.get("/api/state").json()["frame"]["hour"] == FAST + LIVE - 1
        assert len(client.get("/api/history", params={"hours": 5}).json()["frames"]) == 5
        assert client.get("/api/maintenance").json()["items"][0]["sensor"] == SENSOR
        assert client.get(f"/api/what-if/{SENSOR}", params={"days": [1, 30]}).status_code == 200
        assert client.get(f"/api/what-if/{SENSOR}", params={"days": 31}).status_code == 422
        assert client.get("/api/what-if/Z:pm25").status_code == 404
        assert client.post("/api/sensors/Z:pm25/inject").status_code == 404
        assert client.post("/api/control", json={"running": False}).json()["running"] is False
        assert client.post("/api/control", json={"running": True}).json()["running"] is True

        with client.stream("GET", "/api/stream") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            text = "".join(response.iter_text())
        lines = text.strip().split("\n")
        assert lines[1] == "event: tick"
        update = json.loads(lines[2].removeprefix("data: "))
        assert update["status"]["phase"] == "finished"
        assert lines[0] == f"id: {update['events'][0]['id']}"

        event = client.post(f"/api/sensors/{SENSOR}/recalibrate").json()
        assert event["kind"] == "recalibrated"
        assert client.get("/api/state").json()["injections"] == []
        assert client.get("/api/events").json()["events"][0] == event
