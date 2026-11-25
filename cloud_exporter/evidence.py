"""Evidence bundle: everything the triage agent may use about one incident, gathered locally.

The bundle is the complete record of what the model saw. Every section has stable citation
references (``event:<id>``, ``maintenance:<id>``, ``incident:<id>``, ``playbook:<id>``,
``alert:<id>``, ``feature:<name>``, and the section names ``vehicle``, ``unit``, ``fleet``,
``regional``), listed in ``citations``. The agent must cite them, and its output is rejected
when a citation does not resolve. Stored bundles double as the eval set.

``features`` are computed here, in code: the model reads trends and counts, it does not
derive them. ``gaps`` lists what could not be found (404) or was refused, so the agent can
say what is missing instead of guessing. A service that is down raises, and the exporter
answers 503 so the outbox retries; a bundle is never silently partial for that reason.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from fleetops_runtime.errors import DependencyRejected, DependencyUnavailable
from fleetops_runtime.services import ServiceClients
from fleetops_runtime.util import iso

SCHEMA = "fleetops.evidence.v1"
LOOKBACK = timedelta(hours=24)        # vehicle history before the incident
REGION_WINDOW = timedelta(hours=1)    # regional connectivity around now
TREND_WINDOW = timedelta(hours=6)     # battery voltage trend
LOW_VOLTAGE = 11.8                    # same line as rule battery-connectivity-v1
MAX_EVENT_PAGES = 25                  # 200 events per page
MAX_REGION_PAGES = 10
MAX_NOTABLE = 100
MAX_VOLTAGE_READINGS = 96
MAX_MAINTENANCE = 20
SIMILAR_INCIDENTS = 5
MAX_BYTES = 900_000                   # keeps the bundle and its message small

ROUTINE = {"location", "heartbeat", "ignition_on", "ignition_off", "battery_voltage"}
CONNECTIVITY = ("connectivity_lost", "heartbeat_missed")
ACTIONS = (
    "internal_notification", "create_service_case", "schedule_maintenance",
    "fleet_notification", "remote_command", "customer_notification",
)


def parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


class Collector:
    """Service calls that turn 404s and refusals into gaps instead of failures."""

    def __init__(self, services: ServiceClients) -> None:
        self.services = services
        self.gaps: list[dict[str, Any]] = []

    async def get(self, section: str, service: str, path: str, **params: Any) -> Any:
        try:
            result = await self.services.get(service, path, **params)
        except DependencyRejected as exc:
            self.gaps.append({"section": section, "service": service,
                              "reason": f"HTTP {exc.status_code}"})
            return None
        if result is None:
            self.gaps.append({"section": section, "service": service, "reason": "not found"})
        return result

    async def post(self, section: str, service: str, path: str, body: Any,
                   **params: Any) -> Any:
        try:
            return await self.services.request("POST", service, path, json=body,
                                               params=params or None)
        except DependencyRejected as exc:
            self.gaps.append({"section": section, "service": service,
                              "reason": f"HTTP {exc.status_code}"})
            return None

    async def pages(self, section: str, service: str, path: str, max_pages: int,
                    **params: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor = None
        for _ in range(max_pages):
            page = await self.get(section, service, path, limit=200, cursor=cursor, **params)
            if page is None:
                return items
            items += page["items"]
            cursor = page.get("nextCursor")
            if not cursor:
                return items
        self.gaps.append({"section": section, "service": service,
                          "reason": f"truncated after {len(items)} items"})
        return items


# --- deterministic features ----------------------------------------------------------------


def voltage_trend(readings: list[dict[str, Any]], now: datetime) -> float | None:
    """Least-squares slope in volts per hour over the trend window; None with < 3 points."""
    points = [(parse(r["at"]), r["voltage"]) for r in readings]
    points = [((at - now).total_seconds() / 3600, v) for at, v in points
              if at and now - at <= TREND_WINDOW]
    if len(points) < 3:
        return None
    mean_x = sum(x for x, _ in points) / len(points)
    mean_y = sum(y for _, y in points) / len(points)
    spread = sum((x - mean_x) ** 2 for x, _ in points)
    if spread == 0:
        return None
    return round(sum((x - mean_x) * (y - mean_y) for x, y in points) / spread, 3)


def days_since(value: str | None, now: datetime) -> float | None:
    at = parse(value)
    return round((now - at).total_seconds() / 86400, 1) if at else None


def maintenance_features(records: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    def finished(record: dict[str, Any]) -> str | None:
        return record.get("completedAt") or record.get("openedAt")

    done = sorted((r for r in records if finished(r)), key=finished, reverse=True)
    battery = [r for r in done if "battery" in
               f"{r.get('summary', '')} {r.get('resolution', '')}".lower()]
    return {
        "daysSinceLastMaintenance": days_since(finished(done[0]), now) if done else None,
        "daysSinceLastBatteryService": days_since(finished(battery[0]), now) if battery else None,
        "openMaintenanceRecords": sum(r.get("serviceStatus") != "completed" for r in records),
    }


def regional_summary(events: list[dict[str, Any]], region: str | None,
                     vehicle_id: str) -> dict[str, Any]:
    by_region: dict[str, dict[str, set[str]]] = {}
    for event in events:
        bucket = by_region.setdefault(event.get("regionCode") or "unknown",
                                      {kind: set() for kind in CONNECTIVITY})
        bucket[event["eventType"]].add(event["vehicleId"])
    here = by_region.get(region or "", {kind: set() for kind in CONNECTIVITY})
    others = set().union(*here.values()) - {vehicle_id}
    return {
        "region": region,
        "byRegion": {
            name: {f"{kind}Vehicles": len(ids) for kind, ids in kinds.items()}
            for name, kinds in sorted(by_region.items())
        },
        "otherVehiclesAffectedInRegion": len(others),
        "otherAffectedVehicleIds": sorted(others)[:20],
    }


# --- the bundle ----------------------------------------------------------------------------


async def build_evidence(services: ServiceClients, incident: dict[str, Any],
                         now: datetime) -> dict[str, Any]:
    c = Collector(services)
    vehicle_id = incident["vehicleId"]
    start = (parse(incident["firstObservedAt"]) or now) - LOOKBACK
    window = {"from": iso(start), "to": iso(now)}
    trigger_types = sorted({e["eventType"] for e in incident.get("events", [])
                            if e.get("role") == "trigger"})
    event_types = sorted({e["eventType"] for e in incident.get("events", [])}) or ["unknown"]

    context, alerts, maintenance, events, connectivity = await asyncio.gather(
        c.get("vehicle", "vehicle-context-facade", f"/v1/vehicle-context/{vehicle_id}"),
        c.get("alerts", "telematics-event", f"/v1/vehicles/{vehicle_id}/active-alerts"),
        c.get("maintenance", "maintenance-history",
              f"/v1/vehicles/{vehicle_id}/maintenance-records", limit=MAX_MAINTENANCE),
        c.pages("recentEvents", "telematics-event", f"/v1/vehicles/{vehicle_id}/events",
                MAX_EVENT_PAGES, **{"from": window["from"], "to": window["to"]}),
        asyncio.gather(*(
            c.pages("regional", "telematics-event", "/v1/events", MAX_REGION_PAGES,
                    event_type=kind, **{"from": iso(now - REGION_WINDOW), "to": iso(now)})
            for kind in CONNECTIVITY
        )),
    )
    context = context or {}
    if context.get("unavailableDependencies"):
        raise DependencyUnavailable("vehicle-context-facade",
                                    f"missing {context['unavailableDependencies']}")
    profile = context.get("profile") or {}
    unit_id = profile.get("telematicsUnitId")
    fleet_id = profile.get("fleetId")
    region = next((e.get("regionCode") for e in reversed(events) if e.get("regionCode")),
                  profile.get("regionCode"))

    async def none() -> None:
        return None

    last_trigger = next((e["eventId"] for e in reversed(incident.get("events", []))
                         if e.get("role") == "trigger"), None)
    (unit, fleet, sla, contract, fleet_state, impact, similar, approvals, *per_type) = (
        await asyncio.gather(
            c.get("unit", "telematics-unit-master", f"/v1/telematics-units/{unit_id}")
            if unit_id else none(),
            c.get("fleet", "fleet-master", f"/v1/fleets/{fleet_id}") if fleet_id else none(),
            c.get("fleet", "fleet-master", f"/v1/fleets/{fleet_id}/sla") if fleet_id else none(),
            c.get("fleet", "fleet-master", f"/v1/fleets/{fleet_id}/contract")
            if fleet_id else none(),
            c.get("fleet", "digital-twin-context", f"/v1/digital-twins/fleets/{fleet_id}")
            if fleet_id else none(),
            c.get("impact", "digital-twin-context",
                  f"/v1/digital-twins/events/{last_trigger}/downstream-impact")
            if last_trigger else none(),
            c.post("similarIncidents", "incident-search", "/v1/incidents/search",
                   {"eventType": incident.get("caseEventType") or event_types[0],
                    "symptoms": incident.get("symptoms") or event_types,
                    **({"regionCode": region} if region else {})},
                   limit=SIMILAR_INCIDENTS),
            asyncio.gather(*(c.get("actions", "policy-playbook",
                                   f"/v1/actions/{action}/approval-requirement")
                             for action in ACTIONS)),
            *(asyncio.gather(
                c.get("playbooks", "policy-playbook", "/v1/playbooks/search", query=kind),
                c.get("history", "incident-search", "/v1/incident-patterns/resolutions",
                      event_type=kind),
                c.get("history", "incident-search", "/v1/incident-statistics/resolution-time",
                      event_type=kind),
            ) for kind in trigger_types),
        )
    )
    if not unit_id:
        c.gaps.append({"section": "unit", "service": "vehicle-master",
                       "reason": "no telematics unit assigned"})

    matches = (similar or {}).get("items", [])[:SIMILAR_INCIDENTS]
    resolutions = await asyncio.gather(*(
        c.get("similarIncidents", "incident-search",
              f"/v1/incidents/{match['incidentId']}/resolution") for match in matches))
    similar_incidents = [
        {**match, **{k: v for k, v in (resolution or {}).items() if k != "incidentId"}}
        for match, resolution in zip(matches, resolutions)
    ]

    playbooks: dict[str, dict[str, Any]] = {}
    history: dict[str, dict[str, Any]] = {}
    for kind, (found, patterns, timing) in zip(trigger_types, per_type):
        for item in (found or {}).get("items", []):
            best = playbooks.get(item["playbookId"])
            if best is None or item["score"] > best["score"]:
                playbooks[item["playbookId"]] = item
        history[kind] = {"patterns": (patterns or {}).get("patterns", []),
                         "resolutionTime": {k: v for k, v in (timing or {}).items()
                                            if k != "eventType"}}

    events.sort(key=lambda e: (e["observedAt"], e["eventId"]))
    readings = [{"eventId": e["eventId"], "at": e["observedAt"],
                 "voltage": e["payload"].get("voltage")}
                for e in events if e["eventType"] == "battery_voltage"
                and isinstance(e.get("payload", {}).get("voltage"), (int, float))]
    readings = readings[-MAX_VOLTAGE_READINGS:]
    notable = [e for e in events if e["eventType"] not in ROUTINE][-MAX_NOTABLE:]
    counts = Counter(e["eventType"] for e in events)
    records = (maintenance or {}).get("items", [])[:MAX_MAINTENANCE]
    regional = regional_summary([e for page in connectivity for e in page], region, vehicle_id)
    root_causes = Counter(s["rootCause"] for s in similar_incidents if s.get("rootCause"))
    voltages = [r["voltage"] for r in readings]

    features = {
        "batteryVoltageLatest": voltages[-1] if voltages else None,
        "batteryVoltageMin24h": min(voltages) if voltages else None,
        "batteryVoltageTrendVPerHour": voltage_trend(readings, now),
        "lowVoltageReadings24h": sum(v < LOW_VOLTAGE for v in voltages),
        "heartbeatsMissed24h": counts.get("heartbeat_missed", 0),
        "connectivityLost24h": counts.get("connectivity_lost", 0),
        "diagnosticFailures24h": counts.get("diagnostic_failure", 0),
        "dtcCodes24h": sorted({str(e["payload"]["dtcCode"]) for e in events
                               if e["eventType"] == "diagnostic_failure"
                               and e.get("payload", {}).get("dtcCode")}),
        **maintenance_features(records, now),
        "regionOtherVehiclesWithConnectivityIssues1h": regional["otherVehiclesAffectedInRegion"],
        "similarIncidentCount": len(similar_incidents),
        "similarIncidentTopRootCause": root_causes.most_common(1)[0][0] if root_causes else None,
        "firmwareVersion": (unit or {}).get("firmwareVersion"),
    }

    citations: dict[str, str] = {"vehicle": f"vehicle {vehicle_id}"}
    if unit:
        citations["unit"] = f"telematics unit {unit.get('unitId')}"
    if fleet:
        citations["fleet"] = f"fleet {fleet.get('fleetId')}"
    citations["regional"] = f"connectivity events by region, last {REGION_WINDOW}"
    for event in incident.get("events", []):
        citations[f"event:{event['eventId']}"] = f"{event['eventType']} at {event['observedAt']}"
    for event in [*notable, *events]:
        if event["eventType"] in ROUTINE and event["eventType"] != "battery_voltage":
            continue
        citations.setdefault(f"event:{event['eventId']}",
                             f"{event['eventType']} at {event['observedAt']}")
    for alert in (alerts or {}).get("alerts", []):
        citations[f"alert:{alert['alertId']}"] = f"{alert['alertType']} alert"
    for record in records:
        citations[f"maintenance:{record['maintenanceId']}"] = record.get("summary", "maintenance")
    for item in similar_incidents:
        citations[f"incident:{item['incidentId']}"] = item.get("resolution") or "past incident"
    for playbook in playbooks.values():
        citations[f"playbook:{playbook['playbookId']}"] = playbook["title"]
    for name in features:
        citations[f"feature:{name}"] = name
    # Only events kept in the bundle are citable.
    kept = {e["eventId"] for e in [*notable, *incident.get("events", [])]} | {
        r["eventId"] for r in readings}
    citations = {ref: label for ref, label in citations.items()
                 if not ref.startswith("event:") or ref[6:] in kept}

    bundle = {
        "schema": SCHEMA,
        "incidentId": incident["incidentId"],
        "vehicleId": vehicle_id,
        "builtAt": iso(now),
        "incidentSourceVersion": incident["sourceVersion"],
        "window": window,
        "vehicle": {"profile": profile, "operationalState": context.get("operationalState")},
        "unit": unit,
        "fleet": {"profile": fleet, "sla": sla, "contract": contract, "state": fleet_state},
        "activeAlerts": (alerts or {}).get("alerts", []),
        "recentEvents": {"countsByType": dict(sorted(counts.items())),
                         "batteryVoltage": readings, "notable": notable},
        "regional": {"window": {"from": iso(now - REGION_WINDOW), "to": iso(now)}, **regional},
        "maintenance": records,
        "similarIncidents": similar_incidents,
        "history": history,
        "playbooks": sorted(playbooks.values(), key=lambda p: -p["score"]),
        "actions": [a for a in approvals if a],
        "downstreamImpact": impact,
        "features": features,
        "citations": citations,
        "gaps": c.gaps,
    }
    return shrink(bundle)


def size(bundle: dict[str, Any]) -> int:
    return len(json.dumps(bundle, separators=(",", ":")).encode())


def shrink(bundle: dict[str, Any]) -> dict[str, Any]:
    """Keep the bundle under MAX_BYTES by dropping the oldest notable
    events first; the counts and features still describe them."""
    notable = bundle["recentEvents"]["notable"]
    while size(bundle) > MAX_BYTES and notable:
        dropped = notable[: max(1, len(notable) // 2)]
        del notable[: len(dropped)]
        for event in dropped:
            bundle["citations"].pop(f"event:{event['eventId']}", None)
        bundle["gaps"].append({"section": "recentEvents", "service": "cloud-exporter",
                               "reason": f"dropped {len(dropped)} oldest notable events "
                                         "to fit the document size limit"})
    return bundle
