from fleetops_runtime import Operation, ServiceContract


CASE = {
    "caseId": "case_demo_001",
    "vehicleId": "veh_demo_001",
    "recommendationId": "rec_demo_001",
    "status": "open",
    "assignedTeamId": "team_ops",
    "workflowState": "triage",
    "auditTraceId": "trace_demo_001",
    "createdAt": "2026-08-22T12:00:00Z",
}

CONTRACT = ServiceContract(
    slug="case-management",
    title="Case Management Service",
    description="Synthetic operational service cases, assignments, status, and attachments.",
    operations=(
        Operation(
            method="POST",
            path="/v1/cases",
            operation_id="createServiceCase",
            summary="Create a service case",
            response=CASE,
            request={
                "vehicleId": "veh_demo_001",
                "recommendationId": "rec_demo_001",
                "summary": "Inspect low battery voltage",
            },
        ),
        Operation(
            method="PUT",
            path="/v1/cases/{case_id}/status",
            operation_id="updateCase",
            summary="Update case status",
            response={
                **CASE,
                "caseId": "{case_id}",
                "status": "in_progress",
                "workflowState": "assigned",
            },
            request={"status": "in_progress"},
        ),
        Operation(
            method="PUT",
            path="/v1/cases/{case_id}/assignment",
            operation_id="assignCase",
            summary="Assign a case to a team",
            response={**CASE, "caseId": "{case_id}"},
            request={"teamId": "team_ops"},
        ),
        Operation(
            method="POST",
            path="/v1/cases/{case_id}/agent-summaries",
            operation_id="attachAgentSummary",
            summary="Attach an agent summary",
            response={
                "attachmentId": "attachment_demo_001",
                "caseId": "{case_id}",
                "type": "agent_summary",
                "createdAt": "2026-08-22T12:01:00Z",
            },
            request={
                "recommendationId": "rec_demo_001",
                "summary": "Synthetic evidence-backed summary",
                "traceId": "trace_demo_001",
            },
        ),
        Operation(
            method="GET",
            path="/v1/cases/{case_id}/status",
            operation_id="getCaseStatus",
            summary="Get case status",
            response={
                "caseId": "{case_id}",
                "status": "open",
                "assignedTeamId": "team_ops",
                "workflowState": "triage",
                "auditTraceId": "trace_demo_001",
            },
        ),
    ),
)
