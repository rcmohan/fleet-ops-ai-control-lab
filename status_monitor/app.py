"""HTTP API for the status page: GET /v1/status[?since=<epoch seconds>].

    uvicorn status_monitor.app:app --port 8090
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI, Query

from fleetops_runtime.factory import ForwardedPrefixMiddleware

from .monitor import Monitor


def build_app(monitor: Monitor, *, run_background: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(monitor.run()) if run_background else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await monitor.aclose()

    app = FastAPI(
        title="Status Monitor",
        description="Readiness checks for every service, with the last hour kept in memory.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(ForwardedPrefixMiddleware)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"service": "status-monitor", "status": "ok", "version": app.version}

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        return {"service": "status-monitor", "status": "ready", "version": app.version}

    @app.get("/v1/status")
    async def status(
        since: float | None = Query(None, description="Only samples after this epoch time"),
    ) -> dict[str, Any]:
        return monitor.snapshot(since)

    return app


app = build_app(Monitor.from_env())
