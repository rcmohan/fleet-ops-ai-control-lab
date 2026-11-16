"""Calls to other FleetOps services over HTTP. Each service is addressed by its slug."""

from __future__ import annotations

import os
from typing import Any

import httpx

from .errors import DependencyRejected, DependencyUnavailable


def service_url(slug: str) -> str:
    """FLEETOPS_<SLUG>_URL overrides; the default is the Compose service name on port 8080."""
    env = "FLEETOPS_" + slug.upper().replace("-", "_") + "_URL"
    return os.environ.get(env, f"http://{slug}:8080").rstrip("/")


class ServiceClients:
    def __init__(
        self, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 3.0
    ) -> None:
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        slug: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Return the decoded JSON body, or None on 404. Raise on other failures."""
        try:
            response = await self._client.request(
                method, service_url(slug) + path, params=params, json=json, headers=headers
            )
        except httpx.HTTPError as exc:
            raise DependencyUnavailable(slug, type(exc).__name__) from exc
        if response.status_code == 404:
            return None
        if response.status_code >= 500:
            raise DependencyUnavailable(slug, f"HTTP {response.status_code}")
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = response.text
            raise DependencyRejected(slug, response.status_code, body)
        return response.json()

    async def get(self, slug: str, path: str, **params: Any) -> Any:
        clean = {key: value for key, value in params.items() if value is not None}
        return await self.request("GET", slug, path, params=clean or None)

    async def post(self, slug: str, path: str, json: Any, **kwargs: Any) -> Any:
        return await self.request("POST", slug, path, json=json, **kwargs)


class MeshTransport(httpx.AsyncBaseTransport):
    """Routes http://<slug>:8080/... to in-process ASGI apps. Used by tests."""

    def __init__(self, apps: dict[str, Any] | None = None) -> None:
        self.apps: dict[str, Any] = apps if apps is not None else {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        app = self.apps.get(request.url.host)
        if app is None:
            raise httpx.ConnectError(f"no service named {request.url.host}", request=request)
        return await httpx.ASGITransport(app=app).handle_async_request(request)
