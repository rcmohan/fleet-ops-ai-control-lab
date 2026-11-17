"""Correlation rules over telematics signals, and the deterministic response to a match.

telematics-event forwards every non-info event here through its outbox. Each arriving signal
re-evaluates the rules over that vehicle's signals around it, so late or out-of-order events
still complete a pattern. A match becomes an incident. A background worker then scores it
(risk-scoring), asks policy-playbook whether opening a service case is allowed at that risk,
and either opens the case or requests a human approval and waits for the decision. Every
step is written to the incident timeline and, through the outbox, to the audit service.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, Field

from fleetops_runtime import Database, HandlerRegistry, RequestContext, RequestModel, ServiceClients
from fleetops_runtime.db import fetch_all, fetch_one, touch_versioned, update_versioned
from fleetops_runtime.errors import DependencyRejected, DependencyUnavailable, invalid, not_found
from fleetops_runtime.outbox import enqueue
from fleetops_runtime.util import encode_cursor, iso, parse_time

HANDLERS = HandlerRegistry()

SERVICE = "signal-correlation"
ACTIVE = ("detected", "awaiting_approval", "case_opened")
PENDING_WORK = ("detected", "awaiting_approval")
STATUSES = (*ACTIVE, "rejected", "approval_expired", "blocked", "failed", "closed")
APPROVAL_POLL = timedelta(seconds=5)
APPROVAL_TTL_SECONDS = 4 * 3600
WORKER_BATCH = 10
MAX_BACKOFF_SECONDS = 60


# --- Rules -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Signal:
    event_id: str
    event_type: str
    severity: str
    observed_at: datetime
    payload: dict[str, Any]

    @property
    def key(self) -> tuple[datetime, str]:
        return (self.observed_at, self.event_id)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Signal:
        return cls(row["event_id"], row["event_type"], row["severity"], row["observed_at"],
                   row["payload"])


@dataclass(frozen=True)
class RuleStep:
    name: str
    event_type: str
    condition: str  # shown to people; `test` is what runs
    symptom: str
    test: Callable[[dict[str, Any]], bool] = lambda payload: True

    def matches(self, signal: Signal) -> bool:
        return signal.event_type == self.event_type and self.test(signal.payload)


@dataclass(frozen=True)
class Rule:
    rule_id: str
    description: str
    window: timedelta
    steps: tuple[RuleStep, ...]
    action: str
    case_event_type: str

    def watches(self, event_type: str) -> bool:
        return any(step.event_type == event_type for step in self.steps)

    def match(
        self, signals: list[Signal], include: str | None = None
    ) -> list[tuple[RuleStep, Signal]] | None:
        """The steps in order (by observedAt, then eventId), first to last within the window,
        inclusive. Among several matches: earliest finishing, then earliest starting, then
        the lowest event IDs. With `include`, only matches that use that event count."""
        ordered = sorted(signals, key=lambda signal: signal.key)
        best: tuple[Any, ...] | None = None

        def extend(start: int, chosen: list[Signal]) -> None:
            nonlocal best
            if len(chosen) == len(self.steps):
                ids = tuple(signal.event_id for signal in chosen)
                if include is None or include in ids:
                    candidate = (chosen[-1].key, chosen[0].key, ids, list(chosen))
                    if best is None or candidate[:3] < best[:3]:
                        best = candidate
                return
            step = self.steps[len(chosen)]
            for index in range(start, len(ordered)):
                signal = ordered[index]
                if chosen and signal.observed_at - chosen[0].observed_at > self.window:
                    break
                if step.matches(signal):
                    extend(index + 1, [*chosen, signal])

        extend(0, [])
        return None if best is None else list(zip(self.steps, best[3]))


def _number_below(field: str, limit: float) -> Callable[[dict[str, Any]], bool]:
    def test(payload: dict[str, Any]) -> bool:
        value = payload.get(field)
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value < limit

    return test


RULES: tuple[Rule, ...] = (
    Rule(
        rule_id="battery-connectivity-v1",
        description="Low battery, then a missed heartbeat, then a diagnostic failure on one "
        "vehicle: a failing battery rather than a discharged one",
        window=timedelta(minutes=12),
        steps=(
            RuleStep("low_battery", "battery_voltage", "voltage < 11.8", "low_voltage",
                     _number_below("voltage", 11.8)),
            RuleStep("heartbeat_missed", "heartbeat_missed", "any", "missed_heartbeat"),
            RuleStep("diagnostic_failure", "diagnostic_failure", "any", "diagnostic_failure"),
        ),
        action="create_service_case",
        case_event_type="battery_voltage",
    ),
)
RULES_BY_ID = {rule.rule_id: rule for rule in RULES}


def incident_ids(rule: Rule, vehicle_id: str, first_event_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(f"{rule.rule_id}|{vehicle_id}|{first_event_id}".encode()).hexdigest()
    return f"inc_{digest[:20]}", f"trace_{digest[:20]}"


def describe(signal: Signal) -> str:
    if signal.event_type == "battery_voltage":
        return f"battery {signal.payload.get('voltage')} V"
    if signal.event_type == "diagnostic_failure":
        return f"diagnostic {signal.payload.get('dtcCode', 'failure')}"
    return signal.event_type.replace("_", " ")


def case_symptoms(rule: Rule, triggers: list[tuple[str, Signal]]) -> list[str]:
    steps = {step.name: step for step in rule.steps}
    symptoms = {steps[name].symptom for name, _ in triggers if name in steps}
    for _, signal in triggers:
        code = str(signal.payload.get("dtcCode", "")).lower()
        if re.fullmatch(r"[a-z0-9]{2,20}", code):
            symptoms.add(f"dtc_{code}")
    return sorted(symptoms)


# --- Records -----------------------------------------------------------------------------


NULLABLE = ("riskScore", "riskLevel", "policyDecision", "approvalId", "caseId", "lastError")


def to_incident(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "incidentId": row["incident_id"],
        "ruleId": row["rule_id"],
        "vehicleId": row["vehicle_id"],
        "status": row["status"],
        "traceId": row["trace_id"],
        "triggerEventIds": list(row["trigger_event_ids"]),
        "firstObservedAt": iso(row["first_observed_at"]),
        "lastObservedAt": iso(row["last_observed_at"]),
        "riskScore": float(row["risk_score"]) if row["risk_score"] is not None else None,
        "riskLevel": row["risk_level"],
        "policyDecision": row["policy_decision"],
        "approvalId": row["approval_id"],
        "caseId": row["case_id"],
        "lastError": row["last_error"],
        "detectedAt": iso(row["detected_at"]),
        "updatedAt": iso(row["updated_at"]),
        "sourceVersion": row["source_version"],
    }


async def record(
    conn: AsyncConnection,
    incident: dict[str, Any],
    step: str,
    detail: dict[str, Any] | None = None,
    audit: tuple[str, dict[str, Any]] | None = None,
) -> None:
    """Append to the incident timeline and send the same fact to the audit trail."""
    detail = detail or {}
    row = await fetch_one(
        conn,
        "INSERT INTO correlation.incident_steps (incident_id, step, detail) "
        "VALUES (%s, %s, %s) RETURNING step_id, at",
        (incident["incident_id"], step, Jsonb(detail)),
    )
    path, fields = audit or (
        "/v1/audit/system-events", {"source": SERVICE, "eventType": f"incident_{step}"}
    )
    await enqueue(conn, "audit-observability", path, {
        "eventId": f"sigcorr_{incident['incident_id'][4:]}_{row['step_id']}",
        "traceId": incident["trace_id"],
        "occurredAt": iso(row["at"]),
        "payload": {"incidentId": incident["incident_id"], "ruleId": incident["rule_id"],
                    "vehicleId": incident["vehicle_id"], **detail},
        **fields,
    })


async def change(
    conn: AsyncConnection, incident: dict[str, Any], **values: Any
) -> dict[str, Any]:
    """A successful transition clears the retry state."""
    return await update_versioned(
        conn, "correlation.incidents", "incident_id", incident["incident_id"],
        {**values, "attempts": 0, "last_error": None},
    )


# --- Signal intake -----------------------------------------------------------------------


class SignalIn(RequestModel):
    eventId: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    vehicleId: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    eventType: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,47}$")]
    severity: Literal["info", "warning", "critical"]
    observedAt: AwareDatetime
    payload: dict[str, Any] = Field(default_factory=dict)


async def evaluate(conn: AsyncConnection, rule: Rule, vehicle_id: str, signal: Signal) -> str | None:
    rows = await fetch_all(
        conn,
        """
        SELECT s.* FROM correlation.signals s
        WHERE s.vehicle_id = %s AND s.observed_at BETWEEN %s AND %s
          AND NOT EXISTS (SELECT 1 FROM correlation.incident_events e WHERE e.event_id = s.event_id)
        """,
        (vehicle_id, signal.observed_at - rule.window, signal.observed_at + rule.window),
    )
    window = [Signal.from_row(row) for row in rows]
    matched = rule.match(window, include=signal.event_id)
    if matched is None:
        return None
    first, last = matched[0][1], matched[-1][1]

    active = await fetch_one(
        conn,
        "SELECT * FROM correlation.incidents WHERE vehicle_id = %s AND rule_id = %s "
        "AND status = ANY(%s) FOR UPDATE",
        (vehicle_id, rule.rule_id, list(ACTIVE)),
    )
    if active is not None:
        # The vehicle already has an open incident for this rule: the repeat is evidence for it.
        for step, item in matched:
            await conn.execute(
                "INSERT INTO correlation.incident_events (event_id, incident_id, role, step_name) "
                "VALUES (%s, %s, 'supporting', %s)",
                (item.event_id, active["incident_id"], step.name),
            )
        await touch_versioned(conn, "correlation.incidents", "incident_id", active["incident_id"])
        await record(conn, active, "recurred",
                     {"eventIds": [item.event_id for _, item in matched]})
        return active["incident_id"]

    incident_id, trace_id = incident_ids(rule, vehicle_id, first.event_id)
    incident = await fetch_one(
        conn,
        """
        INSERT INTO correlation.incidents (
            incident_id, rule_id, vehicle_id, status, trace_id, trigger_event_ids,
            first_observed_at, last_observed_at, scored_event_id
        ) VALUES (%s, %s, %s, 'detected', %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (incident_id, rule.rule_id, vehicle_id, trace_id,
         [item.event_id for _, item in matched], first.observed_at, last.observed_at,
         last.event_id),
    )
    trigger_ids = {item.event_id for _, item in matched}
    for step, item in matched:
        await conn.execute(
            "INSERT INTO correlation.incident_events (event_id, incident_id, role, step_name) "
            "VALUES (%s, %s, 'trigger', %s)",
            (item.event_id, incident_id, step.name),
        )
    for other in window:
        if other.event_id not in trigger_ids and first.key <= other.key <= last.key:
            await conn.execute(
                "INSERT INTO correlation.incident_events (event_id, incident_id, role) "
                "VALUES (%s, %s, 'supporting')",
                (other.event_id, incident_id),
            )
    await record(conn, incident, "detected", {
        "triggerEventIds": incident["trigger_event_ids"],
        "spanSeconds": int((last.observed_at - first.observed_at).total_seconds()),
    })
    return incident_id


@HANDLERS.operation("ingestSignal", request=SignalIn, nullable=("incidentId",))
async def ingest_signal(ctx: RequestContext) -> dict[str, Any]:
    body: SignalIn = ctx.body
    # Signals for one vehicle are evaluated one at a time, so two halves of a pattern
    # arriving together cannot both miss (or both create) the incident.
    await ctx.db.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"correlation:{body.vehicleId}",)
    )
    row = await fetch_one(
        ctx.db,
        """
        INSERT INTO correlation.signals (event_id, vehicle_id, event_type, severity, observed_at, payload)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (event_id) DO NOTHING
        RETURNING *
        """,
        (body.eventId, body.vehicleId, body.eventType, body.severity, body.observedAt,
         Jsonb(body.payload)),
    )
    if row is None:
        linked = await fetch_one(
            ctx.db, "SELECT incident_id FROM correlation.incident_events WHERE event_id = %s",
            (body.eventId,),
        )
        return {"eventId": body.eventId, "status": "duplicate",
                "incidentId": linked["incident_id"] if linked else None}

    signal = Signal.from_row(row)
    incident_id = None
    for rule in RULES:
        if rule.watches(signal.event_type):
            incident_id = await evaluate(ctx.db, rule, body.vehicleId, signal) or incident_id
    return {"eventId": body.eventId, "status": "recorded", "incidentId": incident_id}


# --- Reads and close ---------------------------------------------------------------------


async def load(conn: AsyncConnection, incident_id: str, *, lock: bool = False) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        "SELECT * FROM correlation.incidents WHERE incident_id = %s" + (" FOR UPDATE" if lock else ""),
        (incident_id,),
    )
    if row is None:
        raise not_found("incident", incident_id)
    return row


@HANDLERS.operation("listCorrelatedIncidents", nullable=NULLABLE)
async def list_incidents(ctx: RequestContext) -> dict[str, Any]:
    status, vehicle_id = ctx.query("status"), ctx.query("vehicle_id")
    if status is not None and status not in STATUSES:
        raise invalid("INVALID_STATUS", f"status must be one of {list(STATUSES)}")
    after, limit = ctx.page(2)
    conditions, params = ["TRUE"], []
    if status:
        conditions.append("status = %s")
        params.append(status)
    if vehicle_id:
        conditions.append("vehicle_id = %s")
        params.append(vehicle_id)
    if after:
        conditions.append("(detected_at, incident_id) < (%s, %s)")
        params += [parse_time(after[0], "cursor"), after[1]]
    rows = await fetch_all(
        ctx.db,
        f"SELECT * FROM correlation.incidents WHERE {' AND '.join(conditions)} "
        "ORDER BY detected_at DESC, incident_id DESC LIMIT %s",
        (*params, limit + 1),
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [to_incident(row) for row in rows],
        "nextCursor": (
            encode_cursor([iso(rows[-1]["detected_at"]), rows[-1]["incident_id"]]) if more else ""
        ),
    }


@HANDLERS.operation("getCorrelatedIncident", nullable=NULLABLE)
async def get_incident(ctx: RequestContext) -> dict[str, Any]:
    incident = await load(ctx.db, ctx.path["incident_id"])
    events = await fetch_all(
        ctx.db,
        """
        SELECT s.*, e.role, e.step_name FROM correlation.incident_events e
        JOIN correlation.signals s USING (event_id)
        WHERE e.incident_id = %s ORDER BY s.observed_at, s.event_id
        """,
        (incident["incident_id"],),
    )
    steps = await fetch_all(
        ctx.db,
        "SELECT step, at, detail FROM correlation.incident_steps WHERE incident_id = %s "
        "ORDER BY step_id",
        (incident["incident_id"],),
    )
    return {
        **to_incident(incident),
        "events": [
            {
                "eventId": row["event_id"],
                "eventType": row["event_type"],
                "severity": row["severity"],
                "observedAt": iso(row["observed_at"]),
                "payload": row["payload"],
                "role": row["role"],
                "ruleStep": row["step_name"],
            }
            for row in events
        ],
        "timeline": [
            {"step": row["step"], "at": iso(row["at"]), "detail": row["detail"]} for row in steps
        ],
    }


class Close(RequestModel):
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


@HANDLERS.operation("closeCorrelatedIncident", request=Close, nullable=NULLABLE)
async def close_incident(ctx: RequestContext) -> dict[str, Any]:
    incident = await load(ctx.db, ctx.path["incident_id"], lock=True)
    if incident["status"] == "closed":
        return to_incident(incident)
    closed = await change(ctx.db, incident, status="closed", closed_reason=ctx.body.reason)
    await record(ctx.db, closed, "closed", {"from": incident["status"], "reason": ctx.body.reason})
    return to_incident(closed)


@HANDLERS.operation("listCorrelationRules")
async def list_rules(ctx: RequestContext) -> dict[str, Any]:
    return {
        "items": [
            {
                "ruleId": rule.rule_id,
                "description": rule.description,
                "windowMinutes": int(rule.window.total_seconds() // 60),
                "steps": [{"name": step.name, "eventType": step.event_type,
                           "condition": step.condition} for step in rule.steps],
                "action": rule.action,
            }
            for rule in RULES
        ]
    }


# --- Response worker ---------------------------------------------------------------------


def action_id(incident: dict[str, Any], rule: Rule) -> str:
    return f"act_{incident['incident_id'][4:]}_{rule.action}"[:64]


async def open_case(
    conn: AsyncConnection, services: ServiceClients, incident: dict[str, Any], rule: Rule
) -> None:
    rows = await fetch_all(
        conn,
        """
        SELECT s.*, e.step_name FROM correlation.incident_events e
        JOIN correlation.signals s USING (event_id)
        WHERE e.incident_id = %s AND e.role = 'trigger' ORDER BY s.observed_at, s.event_id
        """,
        (incident["incident_id"],),
    )
    triggers = [(row["step_name"], Signal.from_row(row)) for row in rows]
    minutes = (incident["last_observed_at"] - incident["first_observed_at"]).total_seconds() / 60
    summary = (
        f"{rule.rule_id}: " + ", ".join(describe(signal) for _, signal in triggers)
        + f" within {minutes:.0f} min. Risk {incident['risk_level']} "
        f"({float(incident['risk_score']):.1f}). Incident {incident['incident_id']}."
    )
    case = await services.post(
        "case-management", "/v1/cases",
        {"vehicleId": incident["vehicle_id"], "summary": summary,
         "eventType": rule.case_event_type, "symptoms": case_symptoms(rule, triggers),
         "traceId": incident["trace_id"]},
        headers={"Idempotency-Key": f"{incident['incident_id']}-case"},
    )
    opened = await change(conn, incident, status="case_opened", case_id=case["caseId"])
    await record(conn, opened, "case_opened", {"caseId": case["caseId"]}, audit=(
        "/v1/audit/action-outcomes",
        {"actionId": action_id(incident, rule), "status": "succeeded"},
    ))


async def respond(conn: AsyncConnection, services: ServiceClients, incident: dict[str, Any]) -> None:
    rule = RULES_BY_ID[incident["rule_id"]]
    if incident["status"] == "awaiting_approval":
        await follow_approval(conn, services, incident, rule)
        return

    if incident["risk_score"] is None:
        priority = await services.get(
            "risk-scoring", f"/v1/risk/events/{incident['scored_event_id']}/composite-priority"
        )
        if priority is None:
            raise DependencyRejected("risk-scoring", 404, "event not found")
        incident = await change(conn, incident, risk_score=priority["priorityScore"],
                                risk_level=priority["urgency"])
        await record(conn, incident, "scored", {
            "eventId": incident["scored_event_id"], "riskScore": priority["priorityScore"],
            "riskLevel": priority["urgency"], "confidence": priority["confidence"],
            "componentScores": priority["componentScores"],
            "scoringPolicyVersion": priority["scoringPolicyVersion"],
        })

    if incident["policy_decision"] is None:
        verdict = await services.get(
            "policy-playbook", "/v1/action-eligibility",
            action_type=rule.action, risk_level=incident["risk_level"],
        )
        if verdict is None:
            raise DependencyRejected("policy-playbook", 404, f"no control for {rule.action}")
        decision = (
            "allowed" if verdict["eligible"]
            else "approval_required" if verdict["approvalRequired"] else "blocked"
        )
        incident = await change(
            conn, incident, policy_decision=decision, policy_id=verdict["policyId"],
            policy_version=verdict["policyVersion"], reviewer_role=verdict["requiredReviewerRole"],
        )
        await record(conn, incident, "policy_evaluated", {
            "actionType": rule.action, "riskLevel": incident["risk_level"],
            "decision": decision, "reason": verdict["reason"],
            "policyVersion": verdict["policyVersion"],
        }, audit=("/v1/audit/policy-decisions",
                  {"policyId": verdict["policyId"], "decision": decision}))

    if incident["policy_decision"] == "allowed":
        await open_case(conn, services, incident, rule)
    elif incident["policy_decision"] == "blocked":
        blocked = await change(conn, incident, status="blocked")
        await record(conn, blocked, "blocked", {"actionType": rule.action}, audit=(
            "/v1/audit/action-outcomes", {"actionId": action_id(incident, rule), "status": "blocked"}
        ))
    else:
        approval = await services.post(
            "approval", "/v1/approvals",
            {"actionId": action_id(incident, rule), "actionType": rule.action,
             "riskLevel": incident["risk_level"], "evidenceTraceId": incident["trace_id"],
             "requestedReviewerRole": incident["reviewer_role"],
             "expiresInSeconds": APPROVAL_TTL_SECONDS},
            headers={"Idempotency-Key": action_id(incident, rule)},
        )
        waiting = await change(conn, incident, status="awaiting_approval",
                               approval_id=approval["approvalId"],
                               next_attempt_at=datetime.now(UTC) + APPROVAL_POLL)
        await record(conn, waiting, "approval_requested", {
            "approvalId": approval["approvalId"], "reviewerRole": incident["reviewer_role"],
            "expiresAt": approval["expiresAt"],
        })


async def follow_approval(
    conn: AsyncConnection, services: ServiceClients, incident: dict[str, Any], rule: Rule
) -> None:
    approval = await services.get("approval", f"/v1/approvals/{incident['approval_id']}")
    if approval is None:
        raise DependencyRejected("approval", 404, f"approval {incident['approval_id']} is missing")
    status = approval["status"]
    if status == "pending":
        await conn.execute(
            "UPDATE correlation.incidents SET next_attempt_at = now() + %s, attempts = 0, "
            "last_error = NULL WHERE incident_id = %s",
            (APPROVAL_POLL, incident["incident_id"]),
        )
        return
    already = await fetch_one(
        conn, "SELECT 1 FROM correlation.incident_steps WHERE incident_id = %s AND step = %s",
        (incident["incident_id"], status),
    )
    if status in ("approved", "rejected") and already is None:  # not again on a retry
        await record(conn, incident, status, {
            "approvalId": approval["approvalId"], "reviewerId": approval["reviewerId"],
            "comments": approval["comments"],
        }, audit=("/v1/audit/human-decisions",
                  {"approvalId": approval["approvalId"], "decision": status}))
    if status == "approved":
        await open_case(conn, services, incident, rule)
        return
    final = "rejected" if status == "rejected" else "approval_expired"
    ended = await change(conn, incident, status=final)
    await record(conn, ended, "no_case", {"reason": final}, audit=(
        "/v1/audit/action-outcomes", {"actionId": action_id(incident, rule), "status": "skipped"}
    ))


async def respond_to(db: Database, services: ServiceClients, incident_id: str) -> None:
    async with db.transaction() as conn:
        incident = await fetch_one(
            conn,
            "SELECT * FROM correlation.incidents WHERE incident_id = %s AND status = ANY(%s) "
            "AND next_attempt_at <= now() FOR UPDATE SKIP LOCKED",
            (incident_id, list(PENDING_WORK)),
        )
        if incident is None:
            return
        try:
            await respond(conn, services, incident)
        except DependencyUnavailable as exc:
            # Progress made before the failure is kept; the next attempt resumes from there.
            attempts = incident["attempts"] + 1
            await conn.execute(
                "UPDATE correlation.incidents SET attempts = %s, last_error = %s, "
                "next_attempt_at = now() + make_interval(secs => %s) WHERE incident_id = %s",
                (attempts, f"{exc.service} unavailable: {exc.reason}",
                 min(2**attempts, MAX_BACKOFF_SECONDS), incident_id),
            )
        except DependencyRejected as exc:
            # A refusal will not change on retry; a person has to look at it.
            current = await load(conn, incident_id)
            failed = await update_versioned(
                conn, "correlation.incidents", "incident_id", incident_id,
                {"status": "failed", "last_error": f"{exc.service} HTTP {exc.status_code}: {exc.body}"[:2000]},
            )
            await record(conn, failed, "failed", {
                "from": current["status"], "dependency": exc.service,
                "dependencyStatus": exc.status_code,
            })


@HANDLERS.worker(interval=1.0)
async def respond_to_incidents(db: Database, services: ServiceClients) -> bool:
    """One pass over due incidents; True when there may be more to do right away."""
    async with db.transaction() as conn:
        due = await fetch_all(
            conn,
            "SELECT incident_id FROM correlation.incidents WHERE status = ANY(%s) "
            "AND next_attempt_at <= now() ORDER BY next_attempt_at LIMIT %s",
            (list(PENDING_WORK), WORKER_BATCH),
        )
    for row in due:
        await respond_to(db, services, row["incident_id"])
    return len(due) == WORKER_BATCH
