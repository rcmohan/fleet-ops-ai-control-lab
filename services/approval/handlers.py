"""Approval requests and decisions.

Reviewer identity comes from the X-Reviewer-Id header and is checked against the reviewer
directory. There is no authentication yet, so any caller can claim any reviewer ID; put an
authenticated access layer in front before this leaves a local machine.
"""

from typing import Annotated, Any, Literal

from pydantic import Field

from fleetops_runtime import HandlerRegistry, RequestContext, RequestModel
from fleetops_runtime.db import fetch_all, fetch_one
from fleetops_runtime.errors import api_error, conflict, forbidden, not_found
from fleetops_runtime.util import encode_cursor, iso, new_id, parse_time

HANDLERS = HandlerRegistry()

OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Role = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
NULLABLE = ("reviewerId", "comments", "decidedAt")

EXPIRE_SQL = """
    UPDATE approvals.approval_requests SET status = 'expired'
    WHERE status = 'pending' AND expires_at <= now() AND {condition}
"""


def to_approval(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "approvalId": row["approval_id"],
        "actionId": row["action_id"],
        "actionType": row["action_type"],
        "status": row["status"],
        "riskLevel": row["risk_level"],
        "requestedReviewerRole": row["requested_reviewer_role"],
        "evidenceTraceId": row["evidence_trace_id"],
        "reviewerId": row["reviewer_id"],
        "comments": row["comments"],
        "requestedAt": iso(row["requested_at"]),
        "expiresAt": iso(row["expires_at"]),
        "decidedAt": iso(row["decided_at"]),
    }


async def load(ctx: RequestContext, approval_id: str, *, lock: bool = False) -> dict[str, Any]:
    await ctx.db.execute(EXPIRE_SQL.format(condition="approval_id = %s"), (approval_id,))
    row = await fetch_one(
        ctx.db,
        "SELECT * FROM approvals.approval_requests WHERE approval_id = %s"
        + (" FOR UPDATE" if lock else ""),
        (approval_id,),
    )
    if row is None:
        raise not_found("approval", approval_id)
    return row


class ApprovalRequest(RequestModel):
    actionId: OpaqueId
    actionType: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
    riskLevel: Literal["low", "medium", "high", "critical"]
    evidenceTraceId: OpaqueId
    requestedReviewerRole: Role
    expiresInSeconds: Annotated[int, Field(ge=60, le=7 * 24 * 3600)] = 3600


@HANDLERS.operation("requestHumanApproval", request=ApprovalRequest, nullable=NULLABLE)
async def request_approval(ctx: RequestContext) -> dict[str, Any]:
    body: ApprovalRequest = ctx.body
    await ctx.db.execute(EXPIRE_SQL.format(condition="action_id = %s"), (body.actionId,))
    pending = await fetch_one(
        ctx.db,
        "SELECT approval_id FROM approvals.approval_requests "
        "WHERE action_id = %s AND status = 'pending'",
        (body.actionId,),
    )
    if pending is not None:
        raise conflict(
            "APPROVAL_ALREADY_PENDING", f"action {body.actionId} already awaits a decision",
            approvalId=pending["approval_id"],
        )
    role_exists = await fetch_one(
        ctx.db, "SELECT 1 FROM approvals.reviewers WHERE role = %s AND active LIMIT 1",
        (body.requestedReviewerRole,),
    )
    if role_exists is None:
        raise api_error(422, "UNKNOWN_REVIEWER_ROLE",
                        f"no active reviewer has role {body.requestedReviewerRole}")
    row = await fetch_one(
        ctx.db,
        """
        INSERT INTO approvals.approval_requests (
            approval_id, action_id, action_type, risk_level, evidence_trace_id,
            requested_reviewer_role, status, expires_at
        ) VALUES (%s, %s, %s, %s, %s, %s, 'pending', now() + make_interval(secs => %s))
        RETURNING *
        """,
        (new_id("apr"), body.actionId, body.actionType, body.riskLevel, body.evidenceTraceId,
         body.requestedReviewerRole, body.expiresInSeconds),
    )
    return to_approval(row)


@HANDLERS.operation("getApprovalStatus", nullable=NULLABLE)
async def get_approval(ctx: RequestContext) -> dict[str, Any]:
    return to_approval(await load(ctx, ctx.path["approval_id"]))


class Decision(RequestModel):
    decision: Literal["approved", "rejected"]
    comments: Annotated[str, Field(max_length=4000)] | None = None


async def reviewer(ctx: RequestContext, reviewer_id: str | None) -> dict[str, Any]:
    if not reviewer_id:
        raise api_error(401, "REVIEWER_REQUIRED", "send the reviewer ID in X-Reviewer-Id")
    row = await fetch_one(
        ctx.db, "SELECT * FROM approvals.reviewers WHERE reviewer_id = %s AND active",
        (reviewer_id,),
    )
    if row is None:
        raise forbidden("UNKNOWN_REVIEWER", f"{reviewer_id} is not an active reviewer")
    return row


@HANDLERS.operation("recordApprovalDecision", request=Decision, nullable=NULLABLE)
async def record_decision(ctx: RequestContext) -> dict[str, Any]:
    person = await reviewer(ctx, ctx.header("x-reviewer-id"))
    approval = await load(ctx, ctx.path["approval_id"], lock=True)
    if approval["status"] == "expired":
        raise conflict("APPROVAL_EXPIRED", "the approval request expired before a decision")
    if approval["status"] != "pending":
        raise conflict(
            "APPROVAL_ALREADY_DECIDED", f"the request was already {approval['status']}",
            status=approval["status"],
        )
    if person["role"] != approval["requested_reviewer_role"]:
        raise forbidden(
            "WRONG_REVIEWER_ROLE",
            f"this request needs a {approval['requested_reviewer_role']}",
        )
    row = await fetch_one(
        ctx.db,
        """
        UPDATE approvals.approval_requests
        SET status = %s, reviewer_id = %s, comments = %s, decided_at = now()
        WHERE approval_id = %s
        RETURNING *
        """,
        (ctx.body.decision, person["reviewer_id"], ctx.body.comments, approval["approval_id"]),
    )
    return to_approval(row)


@HANDLERS.operation("listPendingApprovals")
async def list_pending(ctx: RequestContext) -> dict[str, Any]:
    person = await reviewer(ctx, ctx.query("reviewer_id"))
    await ctx.db.execute(
        EXPIRE_SQL.format(condition="requested_reviewer_role = %s"), (person["role"],)
    )
    after, limit = ctx.page(2)
    params: list[Any] = [person["role"]]
    page_filter = ""
    if after:
        page_filter = "AND (requested_at, approval_id) > (%s, %s)"
        params += [parse_time(after[0], "cursor"), after[1]]
    rows = await fetch_all(
        ctx.db,
        f"""
        SELECT * FROM approvals.approval_requests
        WHERE requested_reviewer_role = %s AND status = 'pending' {page_filter}
        ORDER BY requested_at, approval_id
        LIMIT %s
        """,
        (*params, limit + 1),
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [to_approval(row) for row in rows],
        "nextCursor": (
            encode_cursor([iso(rows[-1]["requested_at"]), rows[-1]["approval_id"]])
            if more else ""
        ),
    }
