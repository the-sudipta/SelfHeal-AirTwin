"""HTTP endpoints of the live twin: state, history, event stream, what-if and commands.

Every handler talks to the :class:`~airtwin.api.events.TwinService` stored on the app; none
touches the twin's internals. Sensors are named ``site:variable``, e.g. ``Dongsi:pm25``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from airtwin import __version__
from airtwin.api.events import Phase, TwinService
from airtwin.config import ApiConfig

router = APIRouter(prefix="/api")


class Control(BaseModel):
    """Body of ``POST /api/control``."""

    running: bool


def _service(request: Request) -> TwinService:
    """The live twin of this app."""
    service: TwinService = request.app.state.service
    return service


def _settings(request: Request) -> ApiConfig:
    """The API settings of this app."""
    settings: ApiConfig = request.app.state.settings
    return settings


def _unknown(sensor: str) -> HTTPException:
    """404 for a sensor the live twin does not have."""
    return HTTPException(status_code=404, detail=f"unknown sensor {sensor!r}")


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    """Liveness and run phase."""
    service = _service(request)
    return {"status": "ok", "version": __version__, "phase": service.phase.value}


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    """Phase, clock and counters of the live run."""
    return _service(request).status()


@router.get("/state")
def state(request: Request) -> dict[str, Any]:
    """Latest frame, network error, maintenance list, events and injected drifts."""
    return _service(request).state()


@router.get("/history")
def history(request: Request, hours: Annotated[int | None, Query(ge=1)] = None) -> dict[str, Any]:
    """The latest hourly frames, oldest first (at most ``api.history_hours``)."""
    return {"frames": _service(request).history(hours)}


@router.get("/maintenance")
def maintenance(request: Request) -> dict[str, Any]:
    """Sensors to recalibrate, highest priority first."""
    return {"items": _service(request).maintenance()}


@router.get("/events")
def events(request: Request, after: Annotated[int, Query(ge=0)] = 0) -> dict[str, Any]:
    """Twin events newer than the event id ``after``, newest first."""
    return {"events": _service(request).events(after)}


@router.get("/what-if/{sensor}")
def what_if(
    request: Request, sensor: str, days: Annotated[list[int] | None, Query()] = None
) -> dict[str, Any]:
    """Projected relative error of one sensor without recalibration, for each ``days`` value."""
    limit = _settings(request).max_what_if_days
    wanted = days or [limit]
    if not all(0 < d <= limit for d in wanted):
        raise HTTPException(status_code=422, detail=f"days must be between 1 and {limit}")
    try:
        return _service(request).what_if(sensor, wanted)
    except KeyError as exc:
        raise _unknown(sensor) from exc


@router.post("/control")
def control(request: Request, body: Control) -> dict[str, Any]:
    """Pause or resume the live ticks."""
    return _service(request).set_running(body.running)


@router.post("/sensors/{sensor}/inject")
def inject(request: Request, sensor: str) -> dict[str, Any]:
    """Inject the configured demonstration drift into one sensor from the next hour."""
    try:
        return _service(request).inject(sensor)
    except KeyError as exc:
        raise _unknown(sensor) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/sensors/{sensor}/recalibrate")
def recalibrate(request: Request, sensor: str) -> dict[str, Any]:
    """Mark a sensor as recalibrated by the field team (the virtual-to-physical loop)."""
    try:
        return _service(request).recalibrate(sensor)
    except KeyError as exc:
        raise _unknown(sensor) from exc


def _message(update: dict[str, Any], last_event: int) -> str:
    """One Server-Sent Events message carrying a state update."""
    data = json.dumps(update, separators=(",", ":"))
    return f"id: {last_event}\nevent: tick\ndata: {data}\n\n"


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    """Server-Sent Events: one ``tick`` message with the new state whenever the twin changes.

    The stream resumes from the ``Last-Event-ID`` header after a reconnect, sends a comment
    line when idle so proxies keep it open, and ends once the run has finished or failed.
    """
    service, settings = _service(request), _settings(request)
    header = request.headers.get("last-event-id", "0")
    start = int(header) if header.isdigit() else 0

    async def messages() -> AsyncIterator[str]:
        last_version, last_event, idle = -1, start, 0.0
        while not await request.is_disconnected():
            if service.version != last_version:
                last_version = service.version
                update = await asyncio.to_thread(service.update, last_event)
                if update["events"]:
                    last_event = update["events"][0]["id"]
                yield _message(update, last_event)
                idle = 0.0
                if service.phase in (Phase.FINISHED, Phase.FAILED):
                    return
            elif idle >= settings.keepalive_s:
                yield ": keepalive\n\n"
                idle = 0.0
            await asyncio.sleep(settings.poll_s)
            idle += settings.poll_s

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(messages(), media_type="text/event-stream", headers=headers)
