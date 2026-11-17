"""FleetOps fleet console: fleets, vehicles, and where they are. Read-only.

Served by the gateway at http://127.0.0.1:8080/fleet/ (Streamlit runs with baseUrlPath=fleet).
To run it on its own from the repository root:

    $env:FLEETOPS_CONSOLE_GATEWAY = "http://127.0.0.1:8080"
    python -m streamlit run fleet_console/app.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import streamlit as st

from console.backend import ServiceError
from fleet_console.backend import STALE_AFTER, FleetBackend, is_stale

st.set_page_config(page_title="FleetOps Fleet", layout="wide")

HEALTH_COLORS = {  # used for the map markers and badges
    "healthy": "#2e9e5b", "warning": "#e08a00", "critical": "#d23c3c", "stale": "#8a8f98",
}
BADGE = {"healthy": "green", "warning": "orange", "critical": "red", "stale": "gray"}


def backend() -> FleetBackend:
    if "fleet_backend" not in st.session_state:
        st.session_state["fleet_backend"] = FleetBackend()
    return st.session_state["fleet_backend"]


def guard(call, *args, **kwargs) -> Any:
    try:
        return call(*args, **kwargs)
    except ServiceError as exc:
        st.error(f"{exc.service}: {exc.code}: {exc.message}")
    return None


def health_of(state: dict[str, Any] | None, now: datetime) -> str:
    return "stale" if is_stale(state, now) else state["healthState"]


def badge(health: str) -> str:
    return f":{BADGE.get(health, 'gray')}[**{health}**]"


def map_points(rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    points = []
    for row in rows:
        location = (row["state"] or {}).get("lastLocation") or {}
        if "latitude" in location and "longitude" in location:
            health = health_of(row["state"], now)
            points.append({"lat": location["latitude"], "lon": location["longitude"],
                           "color": HEALTH_COLORS[health], "vehicle": row["vehicleId"],
                           "health": health})
    return points


def show_map(rows: list[dict[str, Any]], now: datetime) -> None:
    points = map_points(rows, now)
    if not points:
        st.caption("No positions yet. Run the simulator to move the fleet.")
        return
    st.map(points, latitude="lat", longitude="lon", color="color", size=60)
    legend = " · ".join(f":{BADGE[name]}[●] {name}" for name in HEALTH_COLORS)
    st.caption(f"{len(points)} vehicles with a known position. {legend}. Stale means no "
               f"report for {int(STALE_AFTER.total_seconds() // 60)} minutes.")


def vehicle_table(rows: list[dict[str, Any]], now: datetime, key: str) -> str | None:
    table = [
        {"vehicle": r["vehicleId"], "health": health_of(r["state"], now),
         "connectivity": (r["state"] or {}).get("connectivityState", ""),
         "battery V": (r["state"] or {}).get("batteryVoltage"),
         "odometer km": round((r["state"] or {}).get("odometerKm") or 0),
         "last report": (r["state"] or {}).get("observedAt", ""),
         "fleet": r["fleetId"], "region": r["regionCode"], "make": r["make"], "model": r["model"],
         "lifecycle": r["lifecycleStatus"], "service": r["serviceStatus"]}
        for r in rows
    ]
    picked = st.dataframe(table, hide_index=True, use_container_width=True,
                          on_select="rerun", selection_mode="single-row", key=key)
    return table[picked.selection.rows[0]]["vehicle"] if picked.selection.rows else None


# --- vehicle detail ------------------------------------------------------------------------


def vehicle_detail(vehicle_id: str, now: datetime) -> None:
    vehicle = guard(backend().vehicle, vehicle_id)
    if vehicle is None:
        st.warning(f"Vehicle {vehicle_id} not found.")
        return
    state = guard(backend().state, vehicle_id)
    st.divider()
    st.markdown(f"### `{vehicle_id}` · {vehicle['make']} {vehicle['model']} "
                f"{vehicle['modelYear']}")
    health = health_of(state, now)
    cols = st.columns(5)
    cols[0].markdown(f"Health  \n{badge(health)}")
    cols[1].markdown(f"Connectivity  \n{(state or {}).get('connectivityState', '—')}")
    cols[2].markdown(f"Battery  \n{(state or {}).get('batteryVoltage', '—')} V")
    cols[3].markdown(f"Odometer  \n{round((state or {}).get('odometerKm') or 0):,} km")
    cols[4].markdown(f"Last report  \n{(state or {}).get('observedAt', '—')}")

    overview, events, maintenance, incidents = st.tabs(
        ["Overview", "Recent events", "Maintenance", "Incidents"])
    with overview:
        left, right = st.columns(2)
        with left:
            st.markdown("**Vehicle**")
            st.markdown(
                f"VIN `{vehicle['syntheticVin']}` · {vehicle['powertrainType']}  \n"
                f"Fleet `{vehicle['fleetId']}` · region `{vehicle['regionCode']}`  \n"
                f"Lifecycle {vehicle['lifecycleStatus']} · service {vehicle['serviceStatus']} · "
                f"warranty {vehicle['warrantyStatus']} · priority {vehicle['priorityLevel']}"
            )
            unit = guard(backend().unit, vehicle["telematicsUnitId"]) if vehicle[
                "telematicsUnitId"] else None
            st.markdown("**Telematics unit**")
            if unit:
                st.markdown(
                    f"`{unit['unitId']}` {unit['hardwareModel']} · firmware "
                    f"{unit['firmwareVersion']} · {unit['networkCarrier']}  \n"
                    f"{unit['lifecycleStatus']} · remote commands "
                    f"{'eligible' if unit['remoteCommandEligibility'] else 'not eligible'} · "
                    f"{', '.join(unit['capabilities']) or 'no capabilities'}"
                )
            else:
                st.caption("No unit assigned.")
        with right:
            st.markdown("**Active issues and alerts**")
            issues = (state or {}).get("activeIssues") or []
            alerts = guard(backend().alerts, vehicle_id) or []
            for issue in issues:
                st.markdown(f"{badge(issue['severity'])} {issue['issue']} since {issue['since']}")
            if alerts:
                st.dataframe([{"alert": a["alertType"], "severity": a["severity"],
                               "raised": a["raisedAt"], "last seen": a["lastObservedAt"]}
                              for a in alerts], hide_index=True, use_container_width=True)
            if not issues and not alerts:
                st.caption("None.")
            location = (state or {}).get("lastLocation")
            if location:
                st.map([{"lat": location["latitude"], "lon": location["longitude"]}],
                       latitude="lat", longitude="lon", zoom=11, size=80)
    with events:
        items = guard(backend().recent_events, vehicle_id) or []
        st.caption("Last 24 hours, newest first (up to 100).")
        st.dataframe([{"observed": e["observedAt"], "event": e["eventType"],
                       "severity": e["severity"], "payload": json.dumps(e["payload"])}
                      for e in items], hide_index=True, use_container_width=True)
    with maintenance:
        records = guard(backend().maintenance, vehicle_id) or []
        if records:
            st.dataframe([{"opened": r["openedAt"], "type": r["eventType"],
                           "status": r["serviceStatus"], "completed": r["completedAt"],
                           "provider": r["serviceProviderId"], "summary": r["summary"]}
                          for r in records], hide_index=True, use_container_width=True)
        else:
            st.caption("No maintenance records.")
    with incidents:
        found = guard(backend().incidents, vehicle_id) or []
        if not found:
            st.caption("No correlated incidents.")
        for incident in found:
            case = guard(backend().case_status, incident["caseId"]) if incident["caseId"] else None
            st.markdown(
                f"[`{incident['incidentId']}`]({backend().incident_link(incident['incidentId'])}) "
                f"· {incident['status'].replace('_', ' ')} · {incident['ruleId']} · risk "
                f"{incident['riskLevel'] or '—'} · detected {incident['detectedAt']}"
                + (f" · case `{case['caseId']}` {case['status']}" if case else "")
            )
        if found:
            st.caption("Incident links open the operations console.")


# --- pages ---------------------------------------------------------------------------------


def fleets_page(now: datetime) -> None:
    st.title("Fleets")
    rows = guard(backend().fleet_rows, now)
    if rows is None:
        return
    if not rows:
        st.info("No fleets. Load the seed data with `python -m fleetops_seed load`.")
        return
    totals = {name: sum(row[name] for row in rows)
              for name in ("vehicleCount", "healthy", "warning", "critical", "stale",
                           "openIncidents")}
    for column, (label, name) in zip(st.columns(6), (
            ("vehicles", "vehicleCount"), ("healthy", "healthy"), ("warning", "warning"),
            ("critical", "critical"), ("stale", "stale"), ("open incidents", "openIncidents"))):
        column.metric(label, totals[name])
    table = [
        {"fleet": r["fleetId"], "customer": r["customerName"], "tier": r["contractTier"],
         "SLA": r["slaLevel"], "priority": r["priorityLevel"], "vehicles": r["vehicleCount"],
         "healthy": r["healthy"], "warning": r["warning"], "critical": r["critical"],
         "stale": r["stale"], "open incidents": r["openIncidents"],
         "regions": ", ".join(r["operatingRegions"]), "status": r["lifecycleStatus"]}
        for r in rows
    ]
    picked = st.dataframe(table, hide_index=True, use_container_width=True,
                          on_select="rerun", selection_mode="single-row", key="fleet_table")
    if picked.selection.rows:
        st.session_state["fleet_id"] = table[picked.selection.rows[0]]["fleet"]
    fleet_id = st.session_state.get("fleet_id")
    if fleet_id in {row["fleet"] for row in table}:
        fleet_detail(fleet_id, now)
    else:
        st.caption("Select a fleet to see its contract, SLA, vehicles and map.")


def fleet_detail(fleet_id: str, now: datetime) -> None:
    fleet = guard(backend().fleet, fleet_id)
    if fleet is None:
        return
    contract = guard(backend().fleet_contract, fleet_id) or {}
    sla = guard(backend().fleet_sla, fleet_id) or {}
    provider = (guard(backend().provider, fleet["preferredServiceProviderId"])
                if fleet["preferredServiceProviderId"] else None)
    st.divider()
    st.markdown(f"### {fleet['customerName']} · `{fleet_id}`")
    left, right = st.columns(2)
    left.markdown(
        f"Industry {fleet['industryCode']} · declared size {fleet['declaredFleetSize']}  \n"
        f"Contract **{fleet['contractTier']}**"
        + "".join(f" · {key} {value}" for key, value in contract.items()
                  if key not in ("fleetId", "contractTier", "sourceVersion"))
        + f"  \nSLA **{fleet['slaLevel']}**, response target "
        f"{sla.get('responseTargetMinutes', '—')} min · priority {fleet['priorityLevel']}"
    )
    if provider:
        right.markdown(
            f"Preferred provider **{provider['providerName']}** `{provider['providerId']}`  \n"
            f"{provider['dailyCapacity']} jobs/day · ~{provider['averageResponseMinutes']} min "
            f"response · {', '.join(provider['capabilities'])}  \n"
            f"Covers {', '.join(provider['regions'])}"
        )
    else:
        right.caption("No preferred service provider.")
    rows = guard(backend().vehicle_rows, fleet_id, now) or []
    vehicles_tab, map_tab = st.tabs(["Vehicles", "Map"])
    with vehicles_tab:
        selected = vehicle_table(rows, now, key=f"fleet_vehicles_{fleet_id}")
    with map_tab:
        show_map(rows, now)
    if selected:
        vehicle_detail(selected, now)


def vehicles_page(now: datetime) -> None:
    st.title("Vehicles")
    rows = guard(backend().vehicle_rows, None, now)
    if rows is None:
        return
    fleet_col, region_col, life_col, health_col, search_col = st.columns(5)
    fleets = sorted({r["fleetId"] for r in rows if r["fleetId"]})
    regions = sorted({r["regionCode"] for r in rows})
    fleet = fleet_col.selectbox("Fleet", ["all", *fleets])
    region = region_col.selectbox("Region", ["all", *regions])
    lifecycle = life_col.selectbox("Lifecycle", ["all", "active", "inactive", "retired"])
    health = health_col.selectbox("Health", ["all", *HEALTH_COLORS])
    search = search_col.text_input("Vehicle ID contains")
    shown = [
        r for r in rows
        if (fleet == "all" or r["fleetId"] == fleet)
        and (region == "all" or r["regionCode"] == region)
        and (lifecycle == "all" or r["lifecycleStatus"] == lifecycle)
        and (health == "all" or health_of(r["state"], now) == health)
        and search.strip().lower() in r["vehicleId"].lower()
    ]
    st.caption(f"{len(shown)} of {len(rows)} vehicles.")
    selected = vehicle_table(shown, now, key="vehicle_table")
    if selected:
        st.session_state["vehicle_id"] = selected
    vehicle_id = st.session_state.get("vehicle_id") or st.query_params.get("vehicle")
    if vehicle_id:
        vehicle_detail(vehicle_id, now)
    else:
        st.caption("Select a vehicle to see its details.")


def map_page(now: datetime) -> None:
    st.title("Map")
    rows = guard(backend().vehicle_rows, None, now)
    if rows is None:
        return
    shown_health = st.multiselect("Show", list(HEALTH_COLORS), default=list(HEALTH_COLORS))
    show_map([r for r in rows if health_of(r["state"], now) in shown_health], now)


def main() -> None:
    now = datetime.now(UTC)
    with st.sidebar:
        st.markdown("## FleetOps fleet")
        page = st.radio("Page", ["Fleets", "Vehicles", "Map"], label_visibility="collapsed")
        st.button("Refresh", use_container_width=True)
        st.caption(f"Read-only. Incidents and approvals are in the "
                   f"[operations console]({backend().ops_console}).")
    if page == "Fleets":
        fleets_page(now)
    elif page == "Vehicles":
        vehicles_page(now)
    else:
        map_page(now)


main()
