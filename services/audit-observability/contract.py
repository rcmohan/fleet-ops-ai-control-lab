from fleetops_runtime import Operation, ServiceContract


RECEIPT = {"auditEventId": "audit_demo_001", "traceId": "trace_demo_001", "status": "recorded", "recordedAt": "2026-08-22T12:00:00Z"}

CONTRACT = ServiceContract(
    slug="audit-observability",
    title="Audit and Observability Service",
    description="Append-only synthetic audit events and correlated trace retrieval.",
    operations=(
        Operation("POST", "/v1/audit/agent-traces", "recordAgentTrace", "Record an agent trace event", RECEIPT, {"eventId": "audit_demo_001", "traceId": "trace_demo_001", "agentName": "triage-agent", "eventType": "run_completed", "occurredAt": "2026-08-22T12:00:00Z", "payload": {}}),
        Operation("POST", "/v1/audit/tool-calls", "recordToolCall", "Record a tool call", RECEIPT, {"eventId": "audit_demo_002", "traceId": "trace_demo_001", "toolName": "get_vehicle_profile", "status": "succeeded", "occurredAt": "2026-08-22T12:00:00Z", "payload": {}}),
        Operation("POST", "/v1/audit/policy-decisions", "recordPolicyDecision", "Record a policy decision", RECEIPT, {"eventId": "audit_demo_003", "traceId": "trace_demo_001", "policyId": "policy_demo_001", "decision": "approval_required", "occurredAt": "2026-08-22T12:00:00Z", "payload": {}}),
        Operation("POST", "/v1/audit/recommendations", "recordRecommendation", "Record a recommendation", RECEIPT, {"eventId": "audit_demo_004", "traceId": "trace_demo_001", "recommendationId": "rec_demo_001", "actionType": "inspect_vehicle", "occurredAt": "2026-08-22T12:00:00Z", "payload": {}}),
        Operation("POST", "/v1/audit/human-decisions", "recordHumanDecision", "Record a human decision", RECEIPT, {"eventId": "audit_demo_005", "traceId": "trace_demo_001", "approvalId": "apr_demo_001", "decision": "approved", "occurredAt": "2026-08-22T12:05:00Z", "payload": {}}),
        Operation("POST", "/v1/audit/action-outcomes", "recordActionOutcome", "Record an action outcome", RECEIPT, {"eventId": "audit_demo_006", "traceId": "trace_demo_001", "actionId": "act_demo_001", "status": "succeeded", "occurredAt": "2026-08-22T12:06:00Z", "payload": {}}),
        Operation("GET", "/v1/traces/{trace_id}", "getTrace", "Get a correlated trace", {"traceId": "{trace_id}", "events": [{"eventId": "audit_demo_001", "eventType": "run_completed", "occurredAt": "2026-08-22T12:00:00Z"}], "complete": True}),
    ),
)

