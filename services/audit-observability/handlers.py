from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field
from psycopg.types.json import Jsonb

from fleetops_runtime import HandlerRegistry, RequestContext, RequestModel
from fleetops_runtime.db import fetch_all, fetch_one
from fleetops_runtime.errors import conflict, not_found
from fleetops_runtime.util import content_hash, iso

HANDLERS = HandlerRegistry()

OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Name = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")]
TERMINAL_RUN_EVENTS = {"run_completed", "run_failed", "run_cancelled"}


class AuditEvent(RequestModel):
    eventId: OpaqueId
    traceId: OpaqueId
    occurredAt: AwareDatetime
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentTrace(AuditEvent):
    agentName: Name
    eventType: Name


class ToolCall(AuditEvent):
    toolName: Name
    status: Literal["succeeded", "failed", "denied", "timed_out"]


class PolicyDecision(AuditEvent):
    policyId: OpaqueId
    decision: Literal["allowed", "approval_required", "blocked"]


class Recommendation(AuditEvent):
    recommendationId: OpaqueId
    actionType: Name


class HumanDecision(AuditEvent):
    approvalId: OpaqueId
    decision: Literal["approved", "rejected"]


class ActionOutcome(AuditEvent):
    actionId: OpaqueId
    status: Literal["succeeded", "failed", "skipped", "blocked"]


COMMON = {"eventId", "traceId", "occurredAt", "payload"}


def recorder(category: str, event_type: Callable[[Any], str]):
    async def record(ctx: RequestContext) -> dict[str, Any]:
        body = ctx.body
        attributes = body.model_dump(mode="json", exclude=COMMON)
        digest = content_hash(
            [category, body.traceId, iso(body.occurredAt), attributes, body.payload]
        )
        row = await fetch_one(
            ctx.db,
            """
            INSERT INTO audit.audit_events (
                audit_event_id, trace_id, category, event_type, occurred_at, attributes,
                payload, content_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (audit_event_id) DO NOTHING
            RETURNING audit_event_id, trace_id, recorded_at
            """,
            (body.eventId, body.traceId, category, event_type(body), body.occurredAt,
             Jsonb(attributes), Jsonb(body.payload), digest),
        )
        status = "recorded"
        if row is None:
            row = await fetch_one(
                ctx.db,
                "SELECT audit_event_id, trace_id, recorded_at, content_hash "
                "FROM audit.audit_events WHERE audit_event_id = %s",
                (body.eventId,),
            )
            if row["content_hash"] != digest:
                raise conflict(
                    "AUDIT_EVENT_CONFLICT", f"audit event {body.eventId} exists with other content"
                )
            status = "duplicate"
        return {
            "auditEventId": row["audit_event_id"],
            "traceId": row["trace_id"],
            "status": status,
            "recordedAt": iso(row["recorded_at"]),
        }

    return record


ROUTES = [
    ("recordAgentTrace", AgentTrace, "agent_trace", lambda b: b.eventType),
    ("recordToolCall", ToolCall, "tool_call", lambda b: f"tool_call.{b.status}"),
    ("recordPolicyDecision", PolicyDecision, "policy_decision",
     lambda b: f"policy_decision.{b.decision}"),
    ("recordRecommendation", Recommendation, "recommendation",
     lambda b: "recommendation.recorded"),
    ("recordHumanDecision", HumanDecision, "human_decision",
     lambda b: f"human_decision.{b.decision}"),
    ("recordActionOutcome", ActionOutcome, "action_outcome",
     lambda b: f"action_outcome.{b.status}"),
]
for operation_id, model, category, event_type in ROUTES:
    HANDLERS.operation(operation_id, request=model)(recorder(category, event_type))


@HANDLERS.operation("getTrace")
async def get_trace(ctx: RequestContext) -> dict[str, Any]:
    rows = await fetch_all(
        ctx.db,
        "SELECT * FROM audit.audit_events WHERE trace_id = %s ORDER BY occurred_at, audit_event_id",
        (ctx.path["trace_id"],),
    )
    if not rows:
        raise not_found("trace", ctx.path["trace_id"])
    return {
        "traceId": ctx.path["trace_id"],
        "events": [
            {
                "eventId": row["audit_event_id"],
                "category": row["category"],
                "eventType": row["event_type"],
                "occurredAt": iso(row["occurred_at"]),
                "recordedAt": iso(row["recorded_at"]),
                "attributes": row["attributes"],
                "payload": row["payload"],
            }
            for row in rows
        ],
        "complete": any(
            row["category"] == "agent_trace" and row["event_type"] in TERMINAL_RUN_EVENTS
            for row in rows
        ),
    }
