"""The FastAPI application: the live twin's API under ``/api`` and the web twin at ``/``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from airtwin import __version__
from airtwin.api.events import TwinService
from airtwin.api.routes import router
from airtwin.config import Config
from airtwin.data.datasets import load_long
from airtwin.data.download import verify_all
from airtwin.stream import create_stream
from airtwin.stream.interface import StreamSource
from airtwin.stream.memory_stream import SITE
from airtwin.twin.engine import TwinEngine


def open_live_run(cfg: Config) -> tuple[TwinEngine, StreamSource]:
    """Verify and load the configured dataset; build the twin and its stream.

    The stream runs without delay: the service paces the live ticks itself, so fast-forward
    and pause work the same on both backends.
    """
    api = cfg.api
    verify_all(cfg.data)
    frame, columns = load_long(cfg, api.dataset)
    target = replace(cfg.twin.target(api.dataset), variables=api.variables)
    engine = TwinEngine(cfg.twin, target, sorted(frame[SITE].unique()))
    settings = replace(cfg.stream, replay_delay_s=0.0)
    return engine, create_stream(settings, frame, columns, name=f"live-{api.dataset}")


def create_app(cfg: Config, service: TwinService | None = None) -> FastAPI:
    """Build the app; the live run starts with the server and stops with it."""
    live = service or TwinService(cfg.api, lambda: open_live_run(cfg))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        live.start()
        yield
        live.stop()

    app = FastAPI(
        title="SelfHeal-AirTwin",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.service = live
    app.state.settings = cfg.api
    app.include_router(router)
    if cfg.api.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=cfg.api.web_dir, html=True), name="web")
    return app
