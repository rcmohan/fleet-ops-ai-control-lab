"""FleetOps operations console.

    python -m streamlit run console/app.py      # from the repository root

Incidents raised by signal-correlation, their evidence and audit trail, approval decisions,
case handling, and scripted fault injection. All service calls happen server-side in
console/backend.py; see there for how reviewer identity is handled.
"""

from __future__ import annotations

import json
from typing import Any

import streamlit as st

from console.backend import INCIDENT_STATUSES, Backend, ServiceError

st.set_page_config(page_title="FleetOps Console", layout="wide")

STATUS_COLORS = {
    "detected": "blue", "awaiting_approval": "orange", "case_opened": "green",
    "rejected": "gray", "approval_expired": "gray", "closed": "gray",
    "blocked": "red", "failed": "red", "pending": "orange", "approved": "green",
    "expired": "gray", "open": "blue", "in_progress": "orange", "resolved": "green",
    "cancelled": "gray",
}
CASE_NEXT = {
    "open": ["in_progress", "resolved", "cancelled"],
    "in_progress": ["open", "resolved", "cancelled"],
    "resolved": ["in_progress", "closed"],
}


def backend() -> Backend:
    if "backend" not in st.session_state:
        st.session_state["backend"] = Backend()
    return st.session_state["backend"]


def badge(status: str | None) -> str:
    if not status:
        return "—"
    return f":{STATUS_COLORS.get(status, 'gray')}[**{status.replace('_', ' ')}**]"


def guard(call, *args, **kwargs) -> Any:
    """Run a backend call; show a failure instead of crashing the page."""
    try:
        return call(*args, **kwargs)
    except ServiceError as exc:
        st.error(f"{exc.service}: {exc.code}: {exc.message}")
    except (PermissionError, ValueError) as exc:
        st.error(str(exc))
    return None


def compact(detail: dict[str, Any]) -> str:
    return ", ".join(f"{k}={json.dumps(v)}" for k, v in detail.items()) if detail else ""


# --- incident detail -----------------------------------------------------------------------


def approval_panel(incident: dict[str, Any], reviewer: str) -> None:
    st.markdown("#### Approval")
    if not incident["approvalId"]:
        decision = incident["policyDecision"]
        st.caption("Policy allowed the action without approval." if decision == "allowed"
                   else "No approval requested yet." if decision is None
                   else f"Policy decision: {decision}.")
        return
    approval = guard(backend().approval, incident["approvalId"])
    if approval is None:
        return
    st.markdown(f"{badge(approval['status'])} · `{approval['approvalId']}` · "
                f"{approval['actionType']} at {approval['riskLevel']} risk")
    st.caption(f"Needs a **{approval['requestedReviewerRole']}** · requested "
               f"{approval['requestedAt']} · expires {approval['expiresAt']}")
    if approval["status"] != "pending":
        st.caption(f"Decided by {approval['reviewerId']} at {approval['decidedAt']}"
                   + (f": “{approval['comments']}”" if approval["comments"] else ""))
        return
    with st.form(f"decide-{approval['approvalId']}"):
        comments = st.text_area("Comments", placeholder="Reason for the decision")
        approve, reject = st.columns(2)
        approved = approve.form_submit_button("Approve", type="primary", use_container_width=True)
        rejected = reject.form_submit_button("Reject", use_container_width=True)
    st.caption(f"Acting as **{reviewer}**.")
    if approved or rejected:
        result = guard(backend().decide, approval["approvalId"],
                       "approved" if approved else "rejected", comments, reviewer)
        if result is not None:
            st.success(f"Recorded: {result['status']}. The correlation service picks this up "
                       "within a few seconds; refresh to follow it.")


def case_panel(incident: dict[str, Any]) -> None:
    st.markdown("#### Service case")
    if not incident["caseId"]:
        st.caption("No case yet.")
        return
    case = guard(backend().case_status, incident["caseId"])
    if case is None:
        return
    st.markdown(f"{badge(case['status'])} · `{case['caseId']}` · team "
                f"`{case['assignedTeamId'] or 'unassigned'}` · {case['workflowState']}")
    next_states = CASE_NEXT.get(case["status"], [])
    if not next_states:
        return
    with st.form(f"case-{case['caseId']}"):
        team = st.text_input("Team", value=case["assignedTeamId"] or "team_ops")
        status = st.selectbox("Move to", ["(no change)", *next_states])
        comment = st.text_input("Comment")
        resolution = st.text_input("Resolution (required to resolve)")
        root_cause = st.text_input("Root cause")
        submitted = st.form_submit_button("Update case")
    if submitted:
        if team and team != case["assignedTeamId"]:
            if guard(backend().assign_case, case["caseId"], team) is None:
                return
        if status != "(no change)":
            if guard(backend().update_case, case["caseId"], status, comment, resolution,
                     root_cause) is None:
                return
        st.success("Case updated.")


def close_panel(incident: dict[str, Any]) -> None:
    if incident["status"] == "closed":
        return
    with st.expander("Close incident"):
        st.caption("Closing lets the rule raise a new incident for this vehicle.")
        with st.form(f"close-{incident['incidentId']}"):
            reason = st.text_input("Reason")
            submitted = st.form_submit_button("Close incident")
        if submitted:
            if not reason.strip():
                st.error("Give a reason.")
            elif guard(backend().close_incident, incident["incidentId"], reason) is not None:
                st.success("Incident closed.")


def evidence_tab(incident: dict[str, Any]) -> None:
    rows = [
        {"role": e["role"], "rule step": e["ruleStep"] or "", "event": e["eventType"],
         "severity": e["severity"], "observed": e["observedAt"],
         "payload": json.dumps(e["payload"]), "eventId": e["eventId"]}
        for e in incident["events"]
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)
    rules = {rule["ruleId"]: rule for rule in guard(backend().rules) or []}
    rule = rules.get(incident["ruleId"])
    if rule:
        steps = " → ".join(f"{s['eventType']} ({s['condition']})" for s in rule["steps"])
        st.caption(f"**{rule['ruleId']}**: {rule['description']}. {steps}, within "
                   f"{rule['windowMinutes']} minutes.")


def vehicle_tab(vehicle_id: str) -> None:
    context = guard(backend().vehicle_context, vehicle_id)
    twin = guard(backend().twin, vehicle_id)
    alerts = guard(backend().active_alerts, vehicle_id) or []
    left, right = st.columns(2)
    with left:
        st.markdown("**Profile and fleet**")
        if context:
            profile, fleet = context.get("profile") or {}, context.get("fleet") or {}
            st.markdown(
                f"{profile.get('make', '?')} {profile.get('model', '?')} "
                f"{profile.get('modelYear', '')} · unit `{profile.get('telematicsUnitId')}`  \n"
                f"Fleet `{fleet.get('fleetId')}` {fleet.get('customerName', '')} · SLA "
                f"{fleet.get('slaLevel', '?')} · tier {fleet.get('contractTier', '?')}"
            )
            if context.get("unavailableDependencies"):
                st.warning("Unavailable: " + ", ".join(context["unavailableDependencies"]))
    with right:
        st.markdown("**Digital twin**")
        if twin:
            st.markdown(
                f"{badge(twin['healthState'])} · {twin['connectivityState']} · battery "
                f"{twin['batteryVoltage']} V · {twin['odometerKm']:.0f} km · as of "
                f"{twin['observedAt']}"
            )
        else:
            st.caption("No state yet.")
    st.markdown("**Active alerts**")
    if alerts:
        st.dataframe(
            [{"alert": a["alertType"], "severity": a["severity"], "raised": a["raisedAt"],
              "last seen": a["lastObservedAt"]} for a in alerts],
            hide_index=True, use_container_width=True,
        )
    else:
        st.caption("None.")


def audit_tab(incident: dict[str, Any]) -> None:
    events = guard(backend().trace, incident["traceId"]) or []
    st.caption(f"Trace `{incident['traceId']}`. Records arrive through the outbox, so the "
               "latest step can take a moment to appear.")
    st.dataframe(
        [{"occurred": e["occurredAt"], "category": e["category"], "event": e["eventType"],
          "attributes": compact(e["attributes"])} for e in events],
        hide_index=True, use_container_width=True,
    )


def incident_detail(incident_id: str, reviewer: str) -> None:
    incident = guard(backend().incident, incident_id)
    if incident is None:
        return
    st.divider()
    st.markdown(f"### Incident `{incident['incidentId']}` · vehicle `{incident['vehicleId']}`")
    status, risk, policy, case = st.columns(4)
    status.markdown(f"Status  \n{badge(incident['status'])}")
    risk.markdown("Risk  \n" + (f"**{incident['riskLevel']}** ({incident['riskScore']})"
                                if incident["riskLevel"] else "—"))
    policy.markdown(f"Policy  \n{incident['policyDecision'] or '—'}")
    case.markdown(f"Case  \n`{incident['caseId']}`" if incident["caseId"] else "Case  \n—")
    if incident["lastError"]:
        st.warning(f"Last error: {incident['lastError']}")

    response, evidence, vehicle, audit = st.tabs(["Response", "Evidence", "Vehicle", "Audit trail"])
    with response:
        left, right = st.columns([3, 2])
        with left:
            approval_panel(incident, reviewer)
            case_panel(incident)
            close_panel(incident)
        with right:
            st.markdown("#### Timeline")
            for step in incident["timeline"]:
                st.markdown(f"`{step['at'][11:19]}` **{step['step'].replace('_', ' ')}**  \n"
                            f"<small>{compact(step['detail'])}</small>", unsafe_allow_html=True)
    with evidence:
        evidence_tab(incident)
    with vehicle:
        vehicle_tab(incident["vehicleId"])
    with audit:
        audit_tab(incident)


# --- pages ---------------------------------------------------------------------------------


def incidents_page(reviewer: str) -> None:
    st.title("Incidents")
    status_col, vehicle_col = st.columns([1, 2])
    status = status_col.selectbox("Status", ["all", *INCIDENT_STATUSES])
    vehicle = vehicle_col.text_input("Vehicle ID", placeholder="any")
    items = guard(backend().incidents, None if status == "all" else status, vehicle.strip() or None)
    if items is None:
        return
    counts = {name: sum(item["status"] == name for item in items) for name in INCIDENT_STATUSES}
    for column, name in zip(st.columns(4), ("detected", "awaiting_approval", "case_opened", "failed")):
        column.metric(name.replace("_", " "), counts[name])
    if not items:
        st.info("No incidents. Inject a fault on the Simulate page, or run the simulator with "
                "`--inject battery_connectivity:veh_golden_001@10`.")
        return
    rows = [
        {"incident": i["incidentId"], "vehicle": i["vehicleId"], "status": i["status"],
         "risk": i["riskLevel"], "score": i["riskScore"], "policy": i["policyDecision"],
         "case": i["caseId"], "last signal": i["lastObservedAt"], "detected": i["detectedAt"]}
        for i in items
    ]
    picked = st.dataframe(rows, hide_index=True, use_container_width=True,
                          on_select="rerun", selection_mode="single-row", key="incident_table")
    if picked.selection.rows:
        st.session_state["incident_id"] = rows[picked.selection.rows[0]]["incident"]
    # ?incident=<id> (linked from the fleet console) preselects an incident.
    selected = st.session_state.get("incident_id") or st.query_params.get("incident")
    if selected in {row["incident"] for row in rows}:
        incident_detail(selected, reviewer)
    else:
        st.caption("Select a row to see the incident.")


def approvals_page(reviewer: str) -> None:
    st.title("Approvals")
    st.caption(f"Pending requests for the role of **{reviewer}**.")
    pending = guard(backend().pending_approvals, reviewer)
    if pending is None:
        return
    if not pending:
        st.info("Nothing waiting for this reviewer.")
        return
    by_trace = {i["traceId"]: i for i in guard(backend().incidents) or []}
    rows = [
        {"approval": a["approvalId"], "action": a["actionType"], "risk": a["riskLevel"],
         "incident": by_trace.get(a["evidenceTraceId"], {}).get("incidentId", ""),
         "vehicle": by_trace.get(a["evidenceTraceId"], {}).get("vehicleId", ""),
         "requested": a["requestedAt"], "expires": a["expiresAt"]}
        for a in pending
    ]
    picked = st.dataframe(rows, hide_index=True, use_container_width=True,
                          on_select="rerun", selection_mode="single-row", key="approval_table")
    if picked.selection.rows and rows[picked.selection.rows[0]]["incident"]:
        incident_detail(rows[picked.selection.rows[0]]["incident"], reviewer)
    else:
        st.caption("Select a row to review the incident behind it.")


def simulate_page() -> None:
    st.title("Simulate")
    st.markdown(
        "Injects the scripted **battery_connectivity** fault for one vehicle, ending just "
        "before now: a battery reading of 11.6 V, then 11.4 V, a missed heartbeat, and a "
        "critical diagnostic code P0562 over nine minutes. telematics-event forwards them to "
        "signal-correlation, which should raise an incident within a few seconds."
    )
    with st.form("inject"):
        vehicle_id = st.text_input("Vehicle ID", value="veh_golden_001")
        submitted = st.form_submit_button("Inject fault", type="primary")
    if submitted:
        sent = guard(backend().inject, vehicle_id.strip())
        if sent:
            st.success(f"Sent {len(sent)} events for {vehicle_id}.")
            st.dataframe(
                [{"event": e["eventType"], "observed": e["observedAt"],
                  "payload": json.dumps(e["payload"]), "status": e["status"]} for e in sent],
                hide_index=True, use_container_width=True,
            )
    st.caption("For background traffic from the whole fleet, run `python -m fleetops_sim "
               "--minutes 30 --live`.")


def main() -> None:
    with st.sidebar:
        st.markdown("## FleetOps console")
        page = st.radio("Page", ["Incidents", "Approvals", "Simulate"], label_visibility="collapsed")
        reviewer = st.selectbox("Acting as reviewer", backend().reviewers)
        st.caption("Local console with no login: anyone who can open it can act as these "
                   "reviewers. Keep it bound to 127.0.0.1.")
        st.button("Refresh", use_container_width=True)
    if page == "Incidents":
        incidents_page(reviewer)
    elif page == "Approvals":
        approvals_page(reviewer)
    else:
        simulate_page()


main()
