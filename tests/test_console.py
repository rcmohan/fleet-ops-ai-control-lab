"""Console backend rules and a headless run of the Streamlit app against fake services."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from console.backend import Backend, ServiceError

NOW = datetime(2026, 11, 16, 9, 30, tzinfo=UTC)

INCIDENT = {
    "incidentId": "inc_1", "ruleId": "battery-connectivity-v1", "vehicleId": "veh_golden_001",
    "status": "awaiting_approval", "traceId": "trace_1",
    "triggerEventIds": ["evt_a", "evt_b", "evt_c"],
    "firstObservedAt": "2026-11-16T09:10:00Z", "lastObservedAt": "2026-11-16T09:19:00Z",
    "riskScore": 71.5, "riskLevel": "high", "policyDecision": "approval_required",
    "approvalId": "apr_1", "caseId": None, "lastError": None,
    "detectedAt": "2026-11-16T09:19:01Z", "updatedAt": "2026-11-16T09:19:02Z", "sourceVersion": 4,
}
DETAIL = {
    **INCIDENT,
    "events": [{"eventId": "evt_a", "eventType": "battery_voltage", "severity": "warning",
                "observedAt": "2026-11-16T09:10:00Z", "payload": {"voltage": 11.6},
                "role": "trigger", "ruleStep": "low_battery"}],
    "timeline": [{"step": "detected", "at": "2026-11-16T09:19:01Z", "detail": {}},
                 {"step": "approval_requested", "at": "2026-11-16T09:19:02Z",
                  "detail": {"approvalId": "apr_1"}}],
}
APPROVAL = {
    "approvalId": "apr_1", "actionId": "act_1", "actionType": "create_service_case",
    "status": "pending", "riskLevel": "high", "requestedReviewerRole": "operations_manager",
    "evidenceTraceId": "trace_1", "reviewerId": None, "comments": None,
    "requestedAt": "2026-11-16T09:19:02Z", "expiresAt": "2026-11-16T13:19:02Z", "decidedAt": None,
}
VEHICLE = {"vehicleId": "veh_golden_001", "regionCode": "us-east", "lifecycleStatus": "active",
           "serviceStatus": "in_service"}


class FakeServices:
    """Answers the calls the console makes, and records the writes."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, str, dict, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        slug, path = request.url.host, request.url.path
        if request.method != "GET":
            body = json.loads(request.content)
            self.writes.append((slug, path, body, dict(request.headers)))
            if path.endswith("/decisions"):
                return httpx.Response(200, json={**APPROVAL, "status": body["decision"],
                                                 "reviewerId": request.headers["x-reviewer-id"]})
            if path == "/v1/events":
                return httpx.Response(200, json={"eventId": body["eventId"], "status": "accepted",
                                                 "acceptedAt": "x"})
            return httpx.Response(200, json={})
        routes = {
            ("signal-correlation", "/v1/correlation/incidents"): {"items": [INCIDENT], "nextCursor": ""},
            ("signal-correlation", "/v1/correlation/incidents/inc_1"): DETAIL,
            ("signal-correlation", "/v1/correlation/rules"): {"items": []},
            ("approval", "/v1/approvals/apr_1"): APPROVAL,
            ("approval", "/v1/approvals"): {"items": [APPROVAL], "nextCursor": ""},
            ("audit-observability", "/v1/traces/trace_1"): {"traceId": "trace_1", "events": [],
                                                            "complete": False},
            ("telematics-event", "/v1/vehicles/veh_golden_001/active-alerts"): {
                "vehicleId": "veh_golden_001", "alerts": []},
            ("vehicle-master", "/v1/vehicles/veh_golden_001"): VEHICLE,
        }
        if (slug, path) in routes:
            return httpx.Response(200, json=routes[(slug, path)])
        return httpx.Response(404, json={"detail": {"code": "NOT_FOUND", "message": path}})


def make_backend(services: FakeServices) -> Backend:
    return Backend(url_for=lambda slug: f"http://{slug}", transport=httpx.MockTransport(services),
                   reviewers=("reviewer_ops_001", "reviewer_safety_001"))


def test_decisions_use_only_allowlisted_reviewers() -> None:
    services = FakeServices()
    backend = make_backend(services)
    with pytest.raises(PermissionError):
        backend.decide("apr_1", "approved", None, "reviewer_someone_else")
    with pytest.raises(PermissionError):
        backend.pending_approvals("reviewer_someone_else")
    assert services.writes == []

    decided = backend.decide("apr_1", "approved", "ok", "reviewer_ops_001")
    assert decided["status"] == "approved"
    (_, path, body, headers), = services.writes
    assert path == "/v1/approvals/apr_1/decisions"
    assert body == {"decision": "approved", "comments": "ok"}
    assert headers["x-reviewer-id"] == "reviewer_ops_001"


def test_service_errors_carry_the_typed_code() -> None:
    backend = make_backend(FakeServices())
    assert backend.case_status("case_missing") is None  # 404 where absence is normal
    with pytest.raises(ServiceError) as caught:
        backend.incident("inc_missing")
    assert (caught.value.service, caught.value.status, caught.value.code) == (
        "signal-correlation", 404, "NOT_FOUND"
    )
    unreachable = Backend(url_for=lambda slug: "http://127.0.0.1:9", timeout=0.5)
    with pytest.raises(ServiceError) as caught:
        unreachable.rules()
    assert caught.value.code == "UNREACHABLE"


def test_inject_sends_the_scripted_fault_ending_before_now() -> None:
    services = FakeServices()
    backend = make_backend(services)
    sent = backend.inject("veh_golden_001", now=NOW)
    assert [e["eventType"] for e in sent] == [
        "battery_voltage", "battery_voltage", "heartbeat_missed", "diagnostic_failure"
    ]
    observed = [datetime.fromisoformat(e["observedAt"].replace("Z", "+00:00")) for e in sent]
    assert max(observed) < NOW and max(observed) - min(observed) <= timedelta(minutes=12)
    again = backend.inject("veh_golden_001", now=NOW + timedelta(minutes=30))
    assert not {e["eventId"] for e in sent} & {e["eventId"] for e in again}
    with pytest.raises(ServiceError):
        backend.inject("veh_unknown", now=NOW)


def test_app_shows_an_incident_and_records_a_decision() -> None:
    from streamlit.testing.v1 import AppTest

    services = FakeServices()
    app = AppTest.from_file("../console/app.py", default_timeout=30)
    app.session_state["backend"] = make_backend(services)
    app.session_state["incident_id"] = "inc_1"
    app.run()
    assert not app.exception, app.exception
    text = " ".join(element.value for element in app.markdown)
    assert "inc_1" in text and "awaiting approval" in text
    assert any("operations_manager" in element.value for element in app.caption)

    approve = next(button for button in app.button if button.label == "Approve")
    approve.click().run()
    assert not app.exception, app.exception
    decisions = [w for w in services.writes if w[1].endswith("/decisions")]
    assert len(decisions) == 1 and decisions[0][3]["x-reviewer-id"] == "reviewer_ops_001"
    assert any("Recorded: approved" in element.value for element in app.success)


def test_app_reports_unreachable_services_without_crashing() -> None:
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file("../console/app.py", default_timeout=30)
    app.session_state["backend"] = Backend(url_for=lambda slug: "http://127.0.0.1:9", timeout=0.5)
    app.run()
    assert not app.exception, app.exception
    assert any("UNREACHABLE" in element.value for element in app.error)
