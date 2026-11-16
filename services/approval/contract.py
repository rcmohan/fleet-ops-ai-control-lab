from fleetops_runtime import Operation, Parameter, ServiceContract


APPROVAL = {
    "approvalId": "apr_demo_001",
    "actionId": "act_demo_001",
    "actionType": "fleet_notification",
    "status": "pending",
    "riskLevel": "high",
    "requestedReviewerRole": "operations_manager",
    "evidenceTraceId": "trace_demo_001",
    "reviewerId": None,
    "comments": None,
    "requestedAt": "2026-08-22T12:00:00Z",
    "expiresAt": "2026-08-22T13:00:00Z",
    "decidedAt": None,
}

CONTRACT = ServiceContract(
    slug="approval",
    title="Approval Service",
    description="Human approval requests and reviewer decisions for controlled actions.",
    operations=(
        Operation(
            method="POST",
            path="/v1/approvals",
            operation_id="requestHumanApproval",
            summary="Request human approval",
            response=APPROVAL,
            request={
                "actionId": "act_demo_001",
                "actionType": "fleet_notification",
                "riskLevel": "high",
                "evidenceTraceId": "trace_demo_001",
                "requestedReviewerRole": "operations_manager",
                "expiresInSeconds": 3600,
            },
        ),
        Operation(
            method="GET",
            path="/v1/approvals/{approval_id}",
            operation_id="getApprovalStatus",
            summary="Get approval status",
            response={**APPROVAL, "approvalId": "{approval_id}"},
        ),
        Operation(
            method="POST",
            path="/v1/approvals/{approval_id}/decisions",
            operation_id="recordApprovalDecision",
            summary="Record an approval decision",
            parameters=(
                Parameter(
                    "X-Reviewer-Id",
                    location="header",
                    required=True,
                    description="Synthetic reviewer identity; not authenticated",
                ),
            ),
            response={
                **APPROVAL,
                "approvalId": "{approval_id}",
                "status": "approved",
                "reviewerId": "reviewer_ops_001",
                "comments": "Approved for synthetic execution",
                "decidedAt": "2026-08-22T12:05:00Z",
            },
            request={
                "decision": "approved",
                "comments": "Approved for synthetic execution",
            },
        ),
        Operation(
            method="GET",
            path="/v1/approvals",
            operation_id="listPendingApprovals",
            summary="List pending approvals for a reviewer",
            response={"items": [APPROVAL], "nextCursor": ""},
            parameters=(
                Parameter("reviewer_id", required=True),
                Parameter("cursor"),
                Parameter("limit", schema_type="integer"),
            ),
        ),
    ),
)
