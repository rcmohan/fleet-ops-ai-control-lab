from fleetops_runtime import Operation, Parameter, ServiceContract


CONTRACT = ServiceContract(
    slug="policy-playbook",
    title="Policy and Playbook Service",
    description="Versioned synthetic policies, playbooks, escalation rules, and action controls.",
    operations=(
        Operation(
            method="GET",
            path="/v1/playbooks/search",
            operation_id="searchPlaybooks",
            summary="Search playbooks",
            response={
                "items": [
                    {
                        "playbookId": "pb_demo_001",
                        "title": "Battery Voltage Triage",
                        "score": 0.91,
                        "version": "1.0",
                    }
                ],
                "nextCursor": "",
            },
            parameters=(
                Parameter("query", required=True),
                Parameter("cursor"),
                Parameter("limit", schema_type="integer"),
            ),
        ),
        Operation(
            method="GET",
            path="/v1/policies/{policy_id}",
            operation_id="getPolicy",
            summary="Get a policy version",
            response={
                "policyId": "{policy_id}",
                "title": "Synthetic Remote Action Policy",
                "version": "1.0",
                "status": "active",
                "content": "Dummy policy content",
            },
            parameters=(Parameter("version"),),
        ),
        Operation(
            method="GET",
            path="/v1/escalation-rules",
            operation_id="getEscalationRules",
            summary="Get matching escalation rules",
            response={
                "rules": [
                    {
                        "ruleId": "rule_demo_001",
                        "eventType": "battery_voltage",
                        "severity": "critical",
                        "targetTeam": "safety_ops",
                    }
                ]
            },
            parameters=(
                Parameter("event_type", required=True),
                Parameter("severity", required=True),
            ),
        ),
        Operation(
            method="GET",
            path="/v1/action-eligibility",
            operation_id="getActionEligibility",
            summary="Evaluate action eligibility",
            response={
                "eligible": False,
                "riskLevel": "high",
                "reason": "Human approval required",
                "policyId": "policy_demo_001",
                "policyVersion": "1.0",
            },
            parameters=(
                Parameter("action_type", required=True),
                Parameter("risk_level", required=True),
            ),
        ),
        Operation(
            method="GET",
            path="/v1/actions/{action_type}/approval-requirement",
            operation_id="getRequiredApproval",
            summary="Get required approval for an action",
            response={
                "actionType": "{action_type}",
                "approvalRequired": True,
                "requiredReviewerRole": "operations_manager",
                "policyId": "policy_demo_001",
            },
        ),
    ),
)
