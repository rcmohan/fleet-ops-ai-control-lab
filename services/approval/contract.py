from fleetops_runtime import Operation, Parameter, ServiceContract


APPROVAL = {"approvalId": "apr_demo_001", "actionId": "act_demo_001", "actionType": "fleet_notification", "status": "pending", "riskLevel": "high", "requestedReviewerRole": "operations_manager", "reviewerId": "", "comments": "", "requestedAt": "2026-08-22T12:00:00Z", "decidedAt": ""}

CONTRACT = ServiceContract(
    slug="approval",
    title="Approval Service",
    description="Human approval requests and reviewer decisions for controlled actions.",
    operations=(
        Operation("POST", "/v1/approvals", "requestHumanApproval", "Request human approval", APPROVAL, {"actionId": "act_demo_001", "actionType": "fleet_notification", "riskLevel": "high", "evidenceTraceId": "trace_demo_001", "requestedReviewerRole": "operations_manager"}),
        Operation("GET", "/v1/approvals/{approval_id}", "getApprovalStatus", "Get approval status", {**APPROVAL, "approvalId": "{approval_id}"}),
        Operation("POST", "/v1/approvals/{approval_id}/decisions", "recordApprovalDecision", "Record an approval decision", {**APPROVAL, "approvalId": "{approval_id}", "status": "approved", "reviewerId": "reviewer_demo_001", "comments": "Approved for synthetic execution", "decidedAt": "2026-08-22T12:05:00Z"}, {"decision": "approved", "comments": "Approved for synthetic execution"}),
        Operation("GET", "/v1/approvals", "listPendingApprovals", "List pending approvals for a reviewer", {"items": [APPROVAL], "nextCursor": ""}, parameters=(Parameter("reviewer_id", required=True), Parameter("cursor"), Parameter("limit", schema_type="integer"))),
    ),
)

