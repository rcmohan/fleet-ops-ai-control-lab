from typing import Any

from fleetops_runtime import HandlerRegistry, RequestContext
from fleetops_runtime.db import fetch_all, fetch_one
from fleetops_runtime.errors import invalid, not_found
from fleetops_runtime.util import encode_cursor

HANDLERS = HandlerRegistry()

RISK_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
SEVERITIES = {"info", "warning", "critical"}


@HANDLERS.operation("searchPlaybooks")
async def search_playbooks(ctx: RequestContext) -> dict[str, Any]:
    query = (ctx.query("query") or "").strip()
    if not query:
        raise invalid("EMPTY_QUERY", "query must not be empty")
    after, limit = ctx.page(1, default=10)
    offset = int(after[0]) if after else 0
    rows = await fetch_all(
        ctx.db,
        """
        SELECT playbook_id, title, version, event_types,
               ts_rank(search, websearch_to_tsquery('english', %(q)s)) AS score
        FROM policy.playbooks
        WHERE status = 'active'
          AND (search @@ websearch_to_tsquery('english', %(q)s) OR %(q)s = ANY(event_types))
        ORDER BY score DESC, playbook_id
        OFFSET %(offset)s LIMIT %(limit)s
        """,
        {"q": query, "offset": offset, "limit": limit + 1},
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            {
                "playbookId": row["playbook_id"],
                "title": row["title"],
                "score": round(float(row["score"]), 4),
                "version": row["version"],
                "eventTypes": row["event_types"],
            }
            for row in rows
        ],
        "nextCursor": encode_cursor([offset + limit]) if more else "",
    }


@HANDLERS.operation("getPolicy")
async def get_policy(ctx: RequestContext) -> dict[str, Any]:
    policy_id, version = ctx.path["policy_id"], ctx.query("version")
    if version:
        row = await fetch_one(
            ctx.db, "SELECT * FROM policy.policies WHERE policy_id = %s AND version = %s",
            (policy_id, version),
        )
    else:
        row = await fetch_one(
            ctx.db,
            "SELECT * FROM policy.policies WHERE policy_id = %s AND status = 'active'",
            (policy_id,),
        )
    if row is None:
        raise not_found("policy", f"{policy_id}@{version}" if version else policy_id)
    return {
        "policyId": row["policy_id"],
        "title": row["title"],
        "version": row["version"],
        "status": row["status"],
        "content": row["content"],
    }


@HANDLERS.operation("getEscalationRules")
async def escalation_rules(ctx: RequestContext) -> dict[str, Any]:
    severity = ctx.query("severity")
    if severity not in SEVERITIES:
        raise invalid("INVALID_SEVERITY", f"severity must be one of {sorted(SEVERITIES)}")
    rows = await fetch_all(
        ctx.db,
        """
        SELECT * FROM policy.escalation_rules
        WHERE active AND severity = %s AND (event_type = %s OR event_type = '*')
        ORDER BY (event_type = '*'), response_target_minutes, rule_id
        """,
        (severity, ctx.query("event_type")),
    )
    return {
        "rules": [
            {
                "ruleId": row["rule_id"],
                "eventType": row["event_type"],
                "severity": row["severity"],
                "targetTeam": row["target_team"],
                "responseTargetMinutes": row["response_target_minutes"],
                "policyId": row["policy_id"],
            }
            for row in rows
        ]
    }


async def action_control(ctx: RequestContext, action_type: str) -> dict[str, Any]:
    row = await fetch_one(
        ctx.db, "SELECT * FROM policy.action_controls WHERE action_type = %s", (action_type,)
    )
    if row is None:
        raise not_found("action type", action_type)
    return row


@HANDLERS.operation("getActionEligibility", nullable=("requiredReviewerRole",))
async def action_eligibility(ctx: RequestContext) -> dict[str, Any]:
    risk = ctx.query("risk_level")
    if risk not in RISK_RANK:
        raise invalid("INVALID_RISK_LEVEL", f"risk_level must be one of {list(RISK_RANK)}")
    control = await action_control(ctx, ctx.query("action_type"))
    limit = control["max_autonomous_risk"]
    within_limit = limit is not None and RISK_RANK[risk] <= RISK_RANK[limit]
    if control["approval_mode"] == "blocked":
        eligible, reason, reviewer = False, "Action is not permitted by policy", None
    elif within_limit:
        eligible, reason, reviewer = True, f"Within the autonomous limit ({limit})", None
    else:
        eligible, reason = False, "Human approval required"
        reviewer = control["required_reviewer_role"]
    return {
        "eligible": eligible,
        "riskLevel": risk,
        "reason": reason,
        "approvalRequired": not eligible and control["approval_mode"] == "required",
        "requiredReviewerRole": reviewer,
        "policyId": control["policy_id"],
        "policyVersion": control["policy_version"],
    }


@HANDLERS.operation("getRequiredApproval", nullable=("requiredReviewerRole", "maxAutonomousRisk"))
async def required_approval(ctx: RequestContext) -> dict[str, Any]:
    control = await action_control(ctx, ctx.path["action_type"])
    return {
        "actionType": control["action_type"],
        "approvalMode": control["approval_mode"],
        "approvalRequired": control["approval_mode"] == "required",
        "maxAutonomousRisk": control["max_autonomous_risk"],
        "requiredReviewerRole": control["required_reviewer_role"],
        "policyId": control["policy_id"],
    }
