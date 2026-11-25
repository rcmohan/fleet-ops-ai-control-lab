"""HTTP API of the cloud exporter.

    POST /v1/exports/incident-changes   called by signal-correlation's outbox
    POST /v1/exports/context-sync       sync context now (it also runs on a timer)
    POST /v1/exports/events             read new telematics events now (also on a timer)
    POST /v1/exports/flush              load buffered rows into the sink now (also on a timer)
    GET  /v1/exports/status             what was exported last, and the last error

Errors map onto the outbox's retry rules: 503 when the sink or signal-correlation is down
(the outbox retries with backoff), 410 when the incident no longer exists (the outbox gives
up on that message instead of retrying it forever).

    uvicorn --factory cloud_exporter.app:create_app --port 8095
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from fleetops_runtime.errors import DependencyRejected, DependencyUnavailable, api_error
from fleetops_runtime.factory import ForwardedPrefixMiddleware
from fleetops_runtime.services import ServiceClients

from .exporter import Exporter, IncidentGone
from .sinks import SinkUnavailable, sink_from_env

log = logging.getLogger("fleetops.cloud_exporter")
SERVICE = "cloud-exporter"


class IncidentChange(BaseModel):
    incidentId: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    step: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,47}$")]
    stepId: int
    at: str


def build_app(exporter: Exporter, *, run_background: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(exporter.run()) if run_background else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await exporter.services.aclose()

    app = FastAPI(
        title="Cloud Exporter",
        description="Copies events, incidents, evidence and fleet context from the local "
                    "stack to a sink (a local directory, or BigQuery and Pub/Sub).",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(ForwardedPrefixMiddleware)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"service": SERVICE, "status": "ok", "version": app.version}

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        return {"service": SERVICE, "status": "ready", "version": app.version}

    @app.post("/v1/exports/incident-changes", status_code=202)
    async def incident_change(change: IncidentChange) -> dict[str, Any]:
        try:
            return await exporter.export_incident_change(change.model_dump())
        except IncidentGone:
            raise api_error(410, "INCIDENT_GONE",
                            f"incident {change.incidentId} no longer exists") from None
        except (SinkUnavailable, DependencyUnavailable, DependencyRejected) as exc:
            log.warning("export of %s failed: %s", change.incidentId, exc)
            raise api_error(503, "EXPORT_UNAVAILABLE", str(exc)) from None

    @app.post("/v1/exports/context-sync")
    async def context_sync() -> dict[str, Any]:
        try:
            return await exporter.sync_context()
        except (SinkUnavailable, DependencyUnavailable, DependencyRejected) as exc:
            raise api_error(503, "EXPORT_UNAVAILABLE", str(exc)) from None

    @app.post("/v1/exports/events")
    async def events() -> dict[str, Any]:
        try:
            return await exporter.export_events()
        except (SinkUnavailable, DependencyUnavailable, DependencyRejected) as exc:
            raise api_error(503, "EXPORT_UNAVAILABLE", str(exc)) from None

    @app.post("/v1/exports/flush")
    async def flush() -> dict[str, Any]:
        return await exporter.flush()

    @app.get("/v1/exports/status")
    async def status() -> dict[str, Any]:
        return exporter.status()

    return app


def create_app() -> FastAPI:
    return build_app(Exporter.from_env(sink_from_env(), ServiceClients(timeout=10.0)))
