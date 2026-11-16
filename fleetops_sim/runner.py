"""Drives the vehicle models on a simulated clock and sends their events to telematics-event.

The clock never runs ahead of the wall clock (telematics-event rejects future events). A run
can replay a recent window as fast as the services accept it, then optionally keep going in
real time.
"""

from __future__ import annotations

import asyncio
import hashlib
import heapq
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .model import Event, VehicleSim, seeded
from .scenarios import SCENARIOS

UrlFor = Callable[[str], str]


@dataclass(frozen=True)
class Injection:
    scenario: str
    vehicle_id: str
    minute: float  # minutes after the run's start


@dataclass
class RunConfig:
    start: datetime
    minutes: float                    # simulated window before switching to live (or stopping)
    tick: timedelta = timedelta(minutes=1)
    live: bool = False
    live_minutes: float | None = None  # stop after this long in live mode; None runs until stopped
    seed: str = "sim-v1"
    max_vehicles: int | None = None
    injections: list[Injection] = field(default_factory=list)
    late_share: float = 0.01          # events delivered one tick late, out of order
    concurrency: int = 32


@dataclass
class Stats:
    sent: Counter = field(default_factory=Counter)        # by event type
    outcome: Counter = field(default_factory=Counter)     # accepted / duplicate / rejected code
    failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        total = sum(self.sent.values())
        outcome = ", ".join(f"{k} {v}" for k, v in sorted(self.outcome.items()))
        return f"{total} events ({outcome})"


def event_id(seed: str, event: Event) -> str:
    key = f"{seed}|{event.vehicle_id}|{event.event_type}|{event.observed_at.isoformat()}|" \
          f"{sorted(event.payload.items())}"
    return "evt_" + hashlib.sha256(key.encode()).hexdigest()[:24]


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class Simulator:
    def __init__(self, client: httpx.AsyncClient, url_for: UrlFor, config: RunConfig,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.client = client
        self.url_for = url_for
        self.config = config
        self.clock = clock
        self.stats = Stats()
        self.vehicles: dict[str, VehicleSim] = {}
        self.resume_after: dict[str, datetime] = {}
        self.pending: list[tuple[datetime, int, Event]] = []   # scripted and late events
        self.limit = asyncio.Semaphore(config.concurrency)
        self.rng = seeded(config.seed, "delivery")
        self._order = 0

    # ---- setup ---------------------------------------------------------------------

    async def _get(self, slug: str, path: str, **params: Any) -> Any:
        async with self.limit:
            response = await self.client.get(self.url_for(slug) + path, params=params)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def load_roster(self) -> None:
        vehicles, cursor = [], None
        while True:
            page = await self._get("vehicle-master", "/v1/vehicles", limit=200,
                                   **({"cursor": cursor} if cursor else {}))
            vehicles += page["items"]
            cursor = page["nextCursor"]
            if not cursor:
                break
        injected = {injection.vehicle_id for injection in self.config.injections}
        vehicles.sort(key=lambda v: (v["vehicleId"] not in injected, v["vehicleId"]))
        if self.config.max_vehicles is not None:
            vehicles = vehicles[: self.config.max_vehicles]
        missing = injected - {v["vehicleId"] for v in vehicles}
        if missing:
            raise ValueError(f"scenario vehicles not found: {sorted(missing)}")

        # Resume from the twin's last known position and odometer, and never report
        # anything older than what the twin already has.
        states = await asyncio.gather(*(
            self._get("digital-twin-context", f"/v1/digital-twins/vehicles/{v['vehicleId']}")
            for v in vehicles
        ))
        for vehicle, state in zip(vehicles, states):
            sim = VehicleSim.create(self.config.seed, vehicle, self.config.start, state)
            self.vehicles[sim.vehicle_id] = sim
            if state and state.get("observedAt"):
                self.resume_after[sim.vehicle_id] = datetime.fromisoformat(
                    state["observedAt"].replace("Z", "+00:00"))

        for injection in self.config.injections:
            if injection.scenario not in SCENARIOS:
                raise ValueError(f"unknown scenario {injection.scenario}; "
                                 f"choose from {sorted(SCENARIOS)}")
            at = self.config.start + timedelta(minutes=injection.minute)
            for event in SCENARIOS[injection.scenario](self.vehicles[injection.vehicle_id], at):
                self._schedule(event.observed_at, event)

    def _schedule(self, when: datetime, event: Event) -> None:
        self._order += 1
        heapq.heappush(self.pending, (when, self._order, event))

    # ---- sending -------------------------------------------------------------------

    async def _send(self, event: Event) -> None:
        body = {
            "eventId": event_id(self.config.seed, event),
            "vehicleId": event.vehicle_id,
            "eventType": event.event_type,
            "observedAt": iso(event.observed_at),
            "payload": event.payload,
            "synthetic": True,
        }
        url = self.url_for("telematics-event") + "/v1/events"
        self.stats.sent[event.event_type] += 1
        for attempt in range(4):
            try:
                async with self.limit:
                    response = await self.client.post(url, json=body)
            except httpx.HTTPError as exc:
                error = type(exc).__name__
            else:
                if response.status_code == 200:
                    self.stats.outcome[response.json()["status"]] += 1
                    return
                if response.status_code < 500:
                    detail = response.json().get("detail")
                    code = detail.get("code") if isinstance(detail, dict) else "VALIDATION"
                    self.stats.outcome[f"rejected:{code}"] += 1
                    if len(self.stats.failures) < 20:
                        self.stats.failures.append(f"{body['eventId']} {event.event_type}: {detail}")
                    return
                error = f"HTTP {response.status_code}"
            # Same eventId on every attempt, so a retry after a lost response is a duplicate.
            await asyncio.sleep(0.2 * 2**attempt)
        self.stats.outcome["failed"] += 1
        if len(self.stats.failures) < 20:
            self.stats.failures.append(f"{body['eventId']} {event.event_type}: {error}")

    # ---- clock ---------------------------------------------------------------------

    def _collect(self, now: datetime) -> list[Event]:
        due = []
        for sim in self.vehicles.values():
            cutoff = self.resume_after.get(sim.vehicle_id)
            for event in sim.step(now, self.config.tick):
                if cutoff is not None and event.observed_at <= cutoff:
                    continue  # the twin already has newer data for this vehicle
                if self.rng.random() < self.config.late_share:
                    self._schedule(now + self.config.tick, event)   # arrives a tick late
                else:
                    due.append(event)
        while self.pending and self.pending[0][0] <= now:
            due.append(heapq.heappop(self.pending)[2])
        return due

    async def run(self, progress: Callable[[str], None] = lambda _: None) -> Stats:
        await self.load_roster()
        config = self.config
        now = config.start
        backfill_end = config.start + timedelta(minutes=config.minutes)
        live_end = (backfill_end + timedelta(minutes=config.live_minutes)
                    if config.live and config.live_minutes is not None else None)
        progress(f"{len(self.vehicles)} vehicles from {iso(config.start)}"
                 f"{', then live' if config.live else ''}")
        ticks = 0
        while True:
            now += config.tick
            if not config.live and now > backfill_end:
                break
            if live_end is not None and now > live_end:
                break
            wait = (now - self.clock()).total_seconds()
            if wait > 0:
                if not config.live:
                    break
                await asyncio.sleep(wait)
            events = self._collect(now)
            await asyncio.gather(*(self._send(event) for event in events))
            ticks += 1
            if ticks % 15 == 0 or (config.live and now >= backfill_end):
                progress(f"{iso(now)}  {self.stats.summary()}")
        # Flush anything still held back.
        for _, _, event in sorted(self.pending, key=lambda item: (item[0], item[1])):
            if event.observed_at <= self.clock():
                await self._send(event)
        self.pending.clear()
        return self.stats
