"""Loads a catalog through the services' public APIs, in dependency order.

Re-runnable: a record that already exists (409 ALREADY_EXISTS, or "duplicate" from an
idempotent endpoint) counts as loaded. Existing records are not overwritten; to load a
different seed version, start from empty databases.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from .catalog import Catalog

UrlFor = Callable[[str], str]


def gateway_urls(base: str) -> UrlFor:
    """Services behind the local gateway: http://127.0.0.1:8080/<service>."""
    return lambda slug: f"{base.rstrip('/')}/{slug}"


def mesh_urls(slug: str) -> str:
    """Services addressed by Compose name, as inside the Compose network or the test mesh."""
    return f"http://{slug}:8080"


@dataclass
class Report:
    created: Counter = field(default_factory=Counter)
    existing: Counter = field(default_factory=Counter)
    failures: list[str] = field(default_factory=list)

    def line(self, kind: str) -> str:
        return f"{kind:<12} created {self.created[kind]:>4}  existing {self.existing[kind]:>4}"


class Loader:
    def __init__(self, client: httpx.AsyncClient, url_for: UrlFor, concurrency: int = 16) -> None:
        self.client = client
        self.url_for = url_for
        self.limit = asyncio.Semaphore(concurrency)
        self.report = Report()
        self.new_fleets: set[str] = set()

    async def post(self, kind: str, slug: str, path: str, body: dict[str, Any]) -> bool:
        """Create one record. Returns True when this call created it."""
        payload = {key: value for key, value in body.items() if value is not None}
        async with self.limit:
            try:
                response = await self.client.post(self.url_for(slug) + path, json=payload)
            except httpx.HTTPError as exc:
                self.report.failures.append(f"{kind} {path}: {type(exc).__name__}")
                return False
        if response.status_code == 200:
            if response.json().get("status") == "duplicate":
                self.report.existing[kind] += 1
                return False
            self.report.created[kind] += 1
            return True
        detail = _detail(response)
        if response.status_code == 409 and detail.get("code") == "ALREADY_EXISTS":
            self.report.existing[kind] += 1
            return False
        self.report.failures.append(
            f"{kind} {body.get(_id_key(body), '')}: HTTP {response.status_code} {detail}"
        )
        return False

    async def put(self, kind: str, slug: str, path: str, body: dict[str, Any]) -> None:
        async with self.limit:
            response = await self.client.put(self.url_for(slug) + path, json=body)
        if response.status_code == 200:
            self.report.created[kind] += 1
        else:
            self.report.failures.append(f"{kind} {path}: HTTP {response.status_code} "
                                        f"{_detail(response)}")

    async def phase(self, kind: str, slug: str, path: str, items: list[dict[str, Any]]) -> list[bool]:
        return await asyncio.gather(*(self.post(kind, slug, path, item) for item in items))

    async def load(self, catalog: Catalog, progress: Callable[[str], None] = lambda _: None) -> Report:
        # Order follows the reference checks: fleets need providers, vehicles need fleets
        # and units, maintenance needs vehicles and providers.
        await self.phase("providers", "service-provider-master", "/v1/service-providers",
                         catalog.providers)
        progress(self.report.line("providers"))

        fleets = [{k: v for k, v in f.items()} for f in catalog.fleets]
        created = await self.phase("fleets", "fleet-master", "/v1/fleets", fleets)
        progress(self.report.line("fleets"))
        # Contacts are replaced wholesale, so only set them on fleets created in this run.
        await asyncio.gather(*(
            self.put("contacts", "fleet-master", f"/v1/fleets/{fleet['fleetId']}/escalation-contacts",
                     {"contacts": catalog.fleet_contacts.get(fleet["fleetId"], [])})
            for fleet, new in zip(fleets, created) if new
        ))

        await self.phase("units", "telematics-unit-master", "/v1/telematics-units", catalog.units)
        progress(self.report.line("units"))
        await self.phase("vehicles", "vehicle-master", "/v1/vehicles", catalog.vehicles)
        progress(self.report.line("vehicles"))
        await self.phase("maintenance", "maintenance-history", "/v1/maintenance-records",
                         catalog.maintenance)
        progress(self.report.line("maintenance"))
        await self.phase("incidents", "incident-search", "/v1/incidents", catalog.incidents)
        progress(self.report.line("incidents"))
        return self.report


def _detail(response: httpx.Response) -> Any:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return {"body": response.text[:200]}
    return detail if isinstance(detail, dict) else {"errors": detail}


def _id_key(body: dict[str, Any]) -> str:
    return next((key for key in body if key.endswith("Id")), "")
