from fleetops_runtime import Operation, ServiceContract


RECEIPT = {
    "auditEventId": "audit_demo_001",
    "traceId": "trace_demo_001",
    "status": "recorded",
    "recordedAt": "2026-08-22T12:00:00Z",
}

CONTRACT = ServiceContract(
    slug="audit-observability",
    title="Audit and Observability Service",
    description="Append-only synthetic audit events and correlated trace retrieval.",
    operations=(
        Operation(
            method="POST",
            path="/v1/audit/agent-traces",
            operation_id="recordAgentTrace",
            summary="Record an agent trace event",
            response=RECEIPT,
            request={
                "eventId": "audit_demo_001",
                "traceId": "trace_demo_001",
                "agentName": "triage-agent",
                "eventType": "run_completed",
                "occurredAt": "2026-08-22T12:00:00Z",
                "payload": {},
            },
        ),
        Operation(
            method="POST",
            path="/v1/audit/tool-calls",
            operation_id="recordToolCall",
            summary="Record a tool call",
            response=RECEIPT,
            request={
                "eventId": "audit_demo_002",
                "traceId": "trace_demo_001",
                "toolName": "get_vehicle_profile",
                "status": "succeeded",
                "occurredAt": "2026-08-22T12:00:00Z",
                "payload": {},
            },
        ),
        Operation(
            method="POST",
            path="/v1/audit/policy-decisions",
            operation_id="recordPolicyDecision",
            summary="Record a policy decision",
            response=RECEIPT,
            request={
                "eventId": "audit_demo_003",
                "traceId": "trace_demo_001",
                "policyId": "policy_demo_001",
                "decision": "approval_required",
                "occurredAt": "2026-08-22T12:00:00Z",
                "payload": {},
            },
        ),
        Operation(
            method="POST",
            path="/v1/audit/recommendations",
            operation_id="recordRecommendation",
            summary="Record a recommendation",
            response=RECEIPT,
            request={
                "eventId": "audit_demo_004",
                "traceId": "trace_demo_001",
                "recommendationId": "rec_demo_001",
                "actionType": "inspect_vehicle",
                "occurredAt": "2026-08-22T12:00:00Z",
                "payload": {},
            },
        ),
        Operation(
            method="POST",
            path="/v1/audit/human-decisions",
            operation_id="recordHumanDecision",
            summary="Record a human decision",
            response=RECEIPT,
            request={
                "eventId": "audit_demo_005",
                "traceId": "trace_demo_001",
                "approvalId": "apr_demo_001",
                "decision": "approved",
                "occurredAt": "2026-08-22T12:05:00Z",
                "payload": {},
            },
        ),
        Operation(
            method="POST",
            path="/v1/audit/action-outcomes",
            operation_id="recordActionOutcome",
            summary="Record an action outcome",
            response=RECEIPT,
            request={
                "eventId": "audit_demo_006",
                "traceId": "trace_demo_001",
                "actionId": "act_demo_001",
                "status": "succeeded",
                "occurredAt": "2026-08-22T12:06:00Z",
                "payload": {},
            },
        ),
        Operation(
            method="GET",
            path="/v1/traces/{trace_id}",
            operation_id="getTrace",
            summary="Get a correlated trace",
            response={
                "traceId": "{trace_id}",
                "events": [
                    {
                        "eventId": "audit_demo_001",
                        "eventType": "run_completed",
                        "occurredAt": "2026-08-22T12:00:00Z",
                    }
                ],
                "complete": True,
            },
        ),
    ),
)
