from fleetops_runtime import Operation, Parameter, ServiceContract


INCIDENT = {
    "incidentId": "inc_demo_001",
    "ruleId": "battery-connectivity-v1",
    "vehicleId": "veh_demo_001",
    "status": "awaiting_approval",
    "traceId": "trace_demo_001",
    "triggerEventIds": ["evt_demo_001", "evt_demo_002", "evt_demo_003"],
    "firstObservedAt": "2026-08-22T11:40:00Z",
    "lastObservedAt": "2026-08-22T11:49:00Z",
    "riskScore": 68.5,
    "riskLevel": "high",
    "policyDecision": "approval_required",
    "approvalId": "apr_demo_001",
    "caseId": None,
    "lastError": None,
    "detectedAt": "2026-08-22T11:49:02Z",
    "updatedAt": "2026-08-22T11:49:03Z",
    "sourceVersion": 4,
}

CONTRACT = ServiceContract(
    slug="signal-correlation",
    title="Signal Correlation Service",
    description=(
        "Deterministic correlation rules over telematics signals. A match becomes an incident, "
        "which is scored, checked against policy, and turned into a service case directly or "
        "after a human approval."
    ),
    operations=(
        Operation(
            method="POST",
            path="/v1/correlation/signals",
            operation_id="ingestSignal",
            summary="Record a signal and evaluate the correlation rules",
            response={"eventId": "evt_demo_003", "status": "recorded", "incidentId": "inc_demo_001"},
            request={
                "eventId": "evt_demo_003",
                "vehicleId": "veh_demo_001",
                "eventType": "diagnostic_failure",
                "severity": "critical",
                "observedAt": "2026-08-22T11:49:00Z",
                "payload": {"dtcCode": "P0562"},
            },
        ),
        Operation(
            method="GET",
            path="/v1/correlation/incidents",
            operation_id="listCorrelatedIncidents",
            summary="List correlated incidents, newest first",
            response={"items": [INCIDENT], "nextCursor": ""},
            parameters=(
                Parameter("status"),
                Parameter("vehicle_id"),
                Parameter("cursor"),
                Parameter("limit", schema_type="integer"),
            ),
        ),
        Operation(
            method="GET",
            path="/v1/correlation/incidents/{incident_id}",
            operation_id="getCorrelatedIncident",
            summary="Get an incident with its events and response timeline",
            response={
                **INCIDENT,
                "incidentId": "{incident_id}",
                "events": [
                    {
                        "eventId": "evt_demo_001",
                        "eventType": "battery_voltage",
                        "severity": "warning",
                        "observedAt": "2026-08-22T11:40:00Z",
                        "payload": {"voltage": 11.6},
                        "role": "trigger",
                        "ruleStep": "low_battery",
                    }
                ],
                "timeline": [
                    {"step": "detected", "at": "2026-08-22T11:49:02Z", "detail": {}},
                ],
            },
        ),
        Operation(
            method="POST",
            path="/v1/correlation/incidents/{incident_id}/close",
            operation_id="closeCorrelatedIncident",
            summary="Close an incident so the rule can raise a new one for the vehicle",
            response={**INCIDENT, "incidentId": "{incident_id}", "status": "closed"},
            request={"reason": "Battery replaced under case case_demo_001"},
        ),
        Operation(
            method="GET",
            path="/v1/correlation/rules",
            operation_id="listCorrelationRules",
            summary="List the correlation rules",
            response={
                "items": [
                    {
                        "ruleId": "battery-connectivity-v1",
                        "description": "Low battery, then a missed heartbeat, then a "
                        "diagnostic failure on one vehicle",
                        "windowMinutes": 12,
                        "steps": [{"name": "low_battery", "eventType": "battery_voltage",
                                   "condition": "voltage < 11.8"}],
                        "action": "create_service_case",
                    }
                ]
            },
        ),
    ),
)
