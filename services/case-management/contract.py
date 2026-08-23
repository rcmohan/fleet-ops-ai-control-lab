from fleetops_runtime import Operation, ServiceContract


CASE = {"caseId": "case_demo_001", "vehicleId": "veh_demo_001", "recommendationId": "rec_demo_001", "status": "open", "assignedTeamId": "team_ops", "workflowState": "triage", "auditTraceId": "trace_demo_001", "createdAt": "2026-08-22T12:00:00Z"}

CONTRACT = ServiceContract(
    slug="case-management",
    title="Case Management Service",
    description="Synthetic operational service cases, assignments, status, and attachments.",
    operations=(
        Operation("POST", "/v1/cases", "createServiceCase", "Create a service case", CASE, {"vehicleId": "veh_demo_001", "recommendationId": "rec_demo_001", "summary": "Inspect low battery voltage"}),
        Operation("PUT", "/v1/cases/{case_id}/status", "updateCase", "Update case status", {**CASE, "caseId": "{case_id}", "status": "in_progress", "workflowState": "assigned"}, {"status": "in_progress"}),
        Operation("PUT", "/v1/cases/{case_id}/assignment", "assignCase", "Assign a case to a team", {**CASE, "caseId": "{case_id}"}, {"teamId": "team_ops"}),
        Operation("POST", "/v1/cases/{case_id}/agent-summaries", "attachAgentSummary", "Attach an agent summary", {"attachmentId": "attachment_demo_001", "caseId": "{case_id}", "type": "agent_summary", "createdAt": "2026-08-22T12:01:00Z"}, {"recommendationId": "rec_demo_001", "summary": "Synthetic evidence-backed summary", "traceId": "trace_demo_001"}),
        Operation("GET", "/v1/cases/{case_id}/status", "getCaseStatus", "Get case status", {"caseId": "{case_id}", "status": "open", "assignedTeamId": "team_ops", "workflowState": "triage", "auditTraceId": "trace_demo_001"}),
    ),
)

