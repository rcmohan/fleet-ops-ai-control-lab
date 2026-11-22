# Signal Correlation Service

Owns correlation rules, the signals they read, the incidents they raise, and each incident's response timeline. It contains no model or agent: every decision is a rule, a score from risk-scoring, a policy lookup, or a human approval.

## Flow

1. telematics-event forwards every non-info event to `POST /v1/correlation/signals` through its outbox.
2. Signals for one vehicle are evaluated one at a time (an advisory lock per vehicle). Each new signal re-runs the rules over that vehicle's signals within the rule window around it, so a late or out-of-order event can still complete a pattern.
3. A match creates an incident in `detected`. Its ID is derived from the rule, vehicle and first event. An event belongs to at most one incident. While the vehicle has an active incident for the rule, a new match is attached to it as supporting evidence (`recurred`).
4. A background worker advances `detected` and `awaiting_approval` incidents:
   - `scored`: composite priority from risk-scoring for the last trigger event
   - `policy_evaluated`: `GET /v1/action-eligibility` for the rule's action at that risk level
   - allowed: opens the case (`case_opened`)
   - approval required: requests an approval for the policy's reviewer role (`approval_requested`) and polls it. Approved opens the case; rejected or expired ends as `rejected` or `approval_expired`.
   - blocked by policy: `blocked`
5. A dependency outage is retried with backoff, and progress so far is kept. A dependency that refuses the request marks the incident `failed`, with the reason in `lastError`.
6. `POST /v1/correlation/incidents/{id}/close` closes an incident, after which the rule can raise a new one for that vehicle.

Every step goes to the incident timeline and, through the outbox, to audit-observability under the incident's `traceId`. The same transaction also sends a change notice to `cloud-exporter`, which exports the full incident for the cloud agent. Calls that create something (the approval and the case) send an `Idempotency-Key`, so a retry never creates a second one.

## Rules

| Rule | Pattern | Action |
| --- | --- | --- |
| `battery-connectivity-v1` | battery voltage < 11.8 V, then `heartbeat_missed`, then `diagnostic_failure`, first to last within 12 minutes inclusive | `create_service_case` |

Steps are ordered by `(observedAt, eventId)`. When several sets of events match, the rule picks the set that finishes earliest, then the one that starts earliest, then the lowest event IDs. Rules are defined in code (`RULES` in `handlers.py`) and listed at `GET /v1/correlation/rules`.
