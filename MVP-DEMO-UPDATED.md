# FleetOps AI Control Lab — Updated MVP Demo Implementation Plan

**Status:** Proposed implementation baseline; platform integration must pass Phase 0  
**Date:** 2026-09-06  
**Target:** One governed incident, end to end, on Google Cloud, using synthetic data and mock actions only.

This document incorporates the review of [AGENTIC.md](AGENTIC.md) and [MVP_DEMO_PLAN.md](MVP_DEMO_PLAN.md). It is the proposed source of truth for MVP scope when those documents differ. [AGENTIC_ORIGINAL.md](AGENTIC_ORIGINAL.md) remains the original concept. This revision does not claim that the components below are already implemented or deployed.

## 1. Scope and demonstration

NovaFleet Mobility operates a fictional fleet. One vehicle emits low battery voltage, a missed heartbeat, and a failed remote diagnostic. The system correlates the signals, gathers evidence, forms a cause hypothesis, computes priority, and recommends a service case plus a diagnostic. A deterministic service creates the case immediately, persists a diagnostic approval request, and pauses the workflow. An authenticated reviewer approves or rejects. Approval permits one mock diagnostic; rejection permits none. Every transition is traceable.

The historical diagnostic failure is an input fixture representing an earlier authorized attempt. It is not a command issued by this workflow.

### Golden fixture

| Field | Fixed value |
|---|---|
| Vehicle | `veh_10482`, Aster MetroVan 250, model year 2022 |
| Fleet | `flt_204`, customer tier `strategic` |
| SLA | Critical response 120 minutes; high response 480 minutes |
| Region | `us-southeast` |
| Demo clock | `2026-09-05T18:52:00Z` at analysis |
| Signals | Low battery 11.4V at 18:40; missed heartbeat at 18:45; diagnostic failed at 18:47 |
| Prior history | Two resolved power/connectivity incidents on the same vehicle within the preceding 30 days |
| Playbook | `PB-BATTERY-002`, version `1.0` |
| Score | 87, priority `P1`, under scoring policy `priority-v1` |
| Recommendation | `create_service_case` and `remote_diagnostic` |
| Before approval | Exactly one open case; diagnostic pending; zero diagnostic executions |
| After approval | Exactly one mock diagnostic result |
| After rejection | Case remains open; diagnostic rejected; zero diagnostic executions |
| Always blocked in MVP | `customer_notification`, `firmware_action`, and unknown action types |

The score and outcome assertions are fixed. Model-generated prose may vary while satisfying the schema and evidence requirements.

**Included:** manual scenario injection, about 200 ambient events across 100 vehicles, one correlation rule, one primary playbook, two LLM stages, read-only MCP tools, durable business records, human approval, failure-path tests, and a Streamlit console.

**Deferred:** Pub/Sub and continuous monitoring, Cloud Scheduler, Postgres per service, vector search, BigQuery, customer communication drafting, additional fleet scenarios, recommendation editing/revision/supersession, multi-candidate selection UI, a separate quarantine subsystem, enterprise role administration, React, and real vehicle/customer actions. Tests may submit prohibited action types without implementing those scenarios or executors. `SUPERSEDED` is reserved for Phase 2; `MULTIPLE_CANDIDATES` is a terminal MVP guard result, not an interactive flow.

## 2. Deployment and responsibilities

Four application deployables plus Firestore and managed runtime sessions:

```text
Authenticated reviewer
        |
        v
fleetops-console                    Streamlit on Cloud Run
        | manual inject + analyze       | verified approval decision
        v                               v
fleetops-synth-fn                 fleetops-tools-mcp
FastAPI on Cloud Run             Cloud Run, one container
        |                        - read-only /mcp tool endpoint
        | events                 - private workflow/approval HTTP API
        v                        - policy, persistence, mock execution
     Firestore <-------------------------^
                                        |
                              fleetops-control-agent
                              ADK on Agent Runtime
                              deterministic orchestration
                              + Triage LLM + Recommendation LLM
                                        |
                              managed session/checkpoint storage

All components -> structured logs and traces
Business transitions -> durable audit records in Firestore
```

`fleetops-synth-fn` retains the earlier name but is an ordinary FastAPI Cloud Run service with several routes. Deploy it as a service; do not assume a function entry point exists.

The generator is a shared, versioned Python package used by the synth and tools services. Master-data reads do not make an unnecessary HTTP round trip through the synth service. One MCP container contains logical domain handlers; it does not call 15 separately deployed stubs.

The console explicitly starts analysis after the event batch is committed. Firestore writes do not implicitly invoke the agent. The console passes an analysis ID and a frozen snapshot reference, and stores the returned session/invocation identifiers through the private workflow API.

## 3. Platform proof and dependency decisions

Use ADK graph workflows and human-input interruption as the target orchestration mechanism. ADK documents dynamic workflow composition and human-input patterns; the exact Python SDK/runtime combination must be exercised before relying on restart durability. See [ADK dynamic workflows](https://adk.dev/graphs/dynamic/).

Phase 0 is the first implementation work. Start with the smallest graph that writes one mock receipt, pauses, and resumes after worker recovery on pinned versions. Do not build the full domain repositories or console before this proof. Phase 0 must produce a checked-in `docs/validation/platform-proof.md` containing exact Python, ADK, MCP SDK, Google SDK, and model versions; runtime/model locations; deployment configuration; sanitized commands; and evidence of these checks:

1. A local agent loads a packaged skill and performs a private MCP read.
2. The same minimal agent deploys to Agent Runtime and returns schema-valid output with tool use enabled.
3. A run persists a pending approval, pauses, and exposes the identifiers needed to resume it.
4. Recreating the client and restarting the local worker with persistent sessions preserves the pending run. The deployed integration separately demonstrates resumption using durable state after worker recycling where the platform permits it. Document the test boundary; a browser refresh alone does not prove worker durability.
5. A completed side effect is not repeated when the parent orchestration resumes.
6. A fresh MCP request succeeds after credential expiry/refresh and transport reconnection.
7. The console's authenticated reviewer identity reaches the approval boundary and an unauthorized identity is rejected.
8. Traces can be connected to a persisted business audit record.

Save exact compatible versions in lock/constraints files. Do not use unbounded production dependencies such as `google-adk>=2.5`. The earlier plan's model `gemini-3.5-flash` is the initial candidate; verify availability and tool/schema behavior in the chosen model location, then record the selected ID. Runtime location and model location are separate configuration values. Recheck availability and lifecycle documentation when building rather than inheriting unverified shutdown dates.

If graph pause/resume cannot pass with a supported version, record the limitation and revise the orchestration choice before implementing the full tool catalog. An application-managed approval continuation is a possible fallback, but must be described honestly and meet the same persistence and no-duplicate-action tests. Do not present a new invocation as a proven native checkpoint resume.

## 4. LLM scope and tool permissions

| Component | Model use | Responsibility |
|---|---|---|
| Ingest and correlation | None | Validate, deduplicate, freeze a snapshot, find the configured pattern |
| Context gathering | None | Fetch typed facts and establish an immutable evidence bundle |
| Triage | LLM stage 1 | Form a hypothesis, state uncertainty, identify missing evidence |
| Priority scoring | None | Apply `priority-v1` to trusted facts |
| Recommendation | LLM stage 2 | Select supported actions, explain the computed priority, cite evidence |
| Policy and approval | None | Derive permissions, verify reviewer, enforce transitions |
| Execution and audit | None | Commit mock effects once and record outcomes |
| Explanation evaluation | Optional offline model | Grade explanation quality; never authorize an action |

Priority narration is included in Recommendation. Communication drafting is deferred. Two LLM stages do not imply two model requests: tool and skill calls can require multiple turns. Measure requests, tokens, retries, and latency; do not promise four calls or 2–4 seconds.

### Permissions are enforced in code

The MCP endpoint exposes **only read operations**. Each LLM receives a separate explicit subset of those tools. No model receives approval, execution, audit-writing, reset, generic HTTP, shell, or script-execution tools. Skills are repository-controlled knowledge packages without executable scripts or dynamically enabled mutation tools.

| Caller | Permitted access |
|---|---|
| Triage LLM | Vehicle profile, recent events, prior-incident search, approved knowledge skills |
| Recommendation LLM | Vehicle/fleet/SLA facts, prior-incident resolution, approved knowledge skills; frozen score and evidence in input |
| Deterministic orchestration | Private workflow API for snapshot/incident records, recommendation admission, execution, pending approval reads, and finalization |
| Console backend | Run creation/injection, analysis start/status, evidence views, and approval submission |
| Policy/execution handlers | Authoritative policy decisions and Firestore transactions |
| Human reviewer | Approve/reject eligible pending actions through the authenticated console |

The tools service checks authenticated caller permissions for every private operation. Approval submission is reserved to the console backend; the agent runtime principal cannot record human approval. Tool input cannot supply a trusted caller identity or role.

The runtime orchestrator is trusted application code. Tool filtering limits model capabilities within that application; it is not an OS isolation boundary. Every mutation still validates the persisted action and current policy at the service boundary. Model-produced `riskTier`, `approved`, or `requiresHumanApproval` fields are neither accepted nor authoritative.

## 5. Synthetic data, time, and correlation

### 5.1 Consistent master data

Use an explicit finite catalog of 500 vehicles, 20 fleets, 8 regions, and 100 prior incidents, generated with `sha256(seedVersion + entityType + entityId)`. Pin the golden vehicle, fleet, device, and two historical incidents with fixture overrides. Derive related records from the same catalog so vehicle-to-fleet and vehicle-to-device relationships agree in both directions. Choose make/model pairs together.

Unknown identifiers return a typed `NOT_FOUND` result; do not generate facts for every arbitrary ID. This allows missing-record and invented-ID checks. Persist the seed version on each demo run. IDs use the repository's `veh_`, `flt_`, `tcu_`, `sp_`, and `mtn_` conventions.

Use camelCase JSON fields and explicit units. Preserve vehicle `lifecycleStatus` separately from `serviceStatus`. An adapter maps existing contract examples into the MVP schemas; fields such as customer tier and response targets need explicit extensions where existing contracts only contain classifications.

### 5.2 Manual batch contract

| Route or operation | Behavior |
|---|---|
| Create demo run | Allocate `demoRunId`, seed version, fixture clock, ownership record, and immutable `approvalTtlSeconds` through the tools service |
| `POST /runs/{demoRunId}/tick` | Accept `tickId`; emit a bounded deterministic ambient batch |
| `POST /runs/{demoRunId}/scenario/battery_connectivity` | Accept `injectionId`; write the scripted signals once |
| Analyze run | Console asks tools service to close ingestion and freeze one snapshot, then starts or reconnects to the recorded agent session |
| New demo | Create a new `demoRunId`; do not erase a pending run |
| Cleanup run | Explicit administrative script removes only an identified terminal run and its descendants |

Admission and closure are transactional: ingestion checks that the run remains open when committing; closure requires completed batches. Persist tick/injection operation receipts so a timed-out HTTP retry reuses the original result. The same event ID with the same semantic content is a duplicate; the same ID with different content is a conflict. Receipt timestamps are not part of semantic-content comparison.

Store `eventId`, `vehicleId`, `eventType`, `observedAt`, `ingestedAt`, `payload`, `regionCode`, and `synthetic=true`. Add `validationStatus` and `rejectionReason` to each input record; rejected records are excluded from correlation. If malformed input cannot form an event record, retain its input index and reason in the batch receipt's bounded `rejectedInputs` list. No separate quarantine collection, owner, replay API, or console is required. Use Firestore timestamp values in storage and UTC ISO timestamps at API boundaries. The simulation's `ingestedAt` is distinct from server `receivedAt`.

Tests and demos use a controlled event clock. Approval expiry and execution authorization use server UTC, so a historical fixture date never expires an approval immediately.

### 5.3 Correlation rule `battery-connectivity-v1`

1. Validate event schemas and entity references. Mark invalid inputs as rejected with a reason on the input record or batch receipt; do not silently reinterpret them.
2. Accept simulated lateness `0 <= ingestedAt - observedAt <= 5 minutes`; reject events outside that range with a reason. Reject events later than the frozen demo clock. Sort accepted events by `(observedAt, eventId)` regardless of arrival order.
3. Within each vehicle's snapshot, find a low-battery event with voltage below 11.8V, followed by a missed heartbeat, followed by a diagnostic failure. The first-to-last interval must be at most 12 minutes, inclusive. Equal timestamps are ordered by the event ID tie-breaker.
4. If several triples qualify, select the earliest finishing triple, then earliest starting triple, then lexicographic event IDs. Keep other accepted events as supporting context.
5. Emit at most one incident per vehicle/rule/demo run. Its ID is a hash of `(demoRunId, vehicleId, ruleVersion)`; repeated analysis retrieves the same record. Multiple episodes per vehicle in one run are deferred.
6. Freeze the selected event IDs, snapshot hash, and rule version on the incident. Later injections into a closed run are rejected; a new batch uses a new demo run.
7. If no triple qualifies, persist `NO_INCIDENT`, write a correlation audit record, and finish with zero LLM calls, cases, or approvals.

The first MVP analysis admits one incident for the golden fixture; general queue processing is deferred. If an unexpected batch contains multiple candidates across vehicles, record their IDs on the analysis and finish with `MULTIPLE_CANDIDATES`, zero LLM calls, and zero actions. The console shows the status and advises starting a new run with the supported fixture. Candidate selection, processing queues, and a resumable selection UI are Phase 2 work. Test the guard with a small constructed input; do not add a second demo narrative.

Index accepted events for vehicle/time queries and validate required Firestore indexes against the emulator and deployed database. This is a manual batch simulation of event correlation, not a claim of continuous streaming support.

## 6. Deterministic priority specification

`priority-v1` is a synthetic demonstration rule, not a vehicle safety or real contractual risk model. It uses only immutable event, master-data, and prior-incident facts. LLM hypotheses and self-reported confidence never affect its inputs.

| Component | Rule | Golden points | Maximum |
|---|---|---|---|
| Signal severity | Selected low-battery voltage below 11.0V: 30; otherwise below 11.5V: 20; otherwise below 11.8V: 10 | 20 | 30 |
| SLA urgency | Positive critical response target at most 60 minutes: 35; otherwise at most 120: 25; otherwise at most 480: 15; greater: 5 | 25 | 35 |
| Fleet importance | `strategic`: 20; `premium`: 12; `standard`: 5 | 20 | 20 |
| Recurrence | Prior resolved incidents for this vehicle and category in `[firstSignalAt - 30 days, firstSignalAt)`: 0 -> 0; 1 -> 6; 2 -> 12; 3 or more -> 18 | 12 | 18 |
| Evidence completeness | All three validated signals and required vehicle, fleet, SLA, and history records present: 10 | 10 | 10 |
| **Total** | Sum of components; valid matched incidents can score 30–113 | **87** | **113** |

Priority bands: `P1 >= 80`, `P2 >= 50 and < 80`, `P3 < 50`. The score is points, not a percentage. The golden case is inside P1 rather than at the policy ceiling. SLA urgency measures the response-target classification; it does not claim a measured SLA breach probability. These weights and boundaries are illustrative synthetic policy choices requiring real-world calibration before operational use. `priority-v1` is still an unimplemented draft; freeze this definition in the Phase 1 fixture baseline before comparing results across builds.

Missing required context, failed history retrieval, invalid voltage, non-positive SLA targets, or unknown tier produces `INSUFFICIENT_CONTEXT`, a null score, and manual review with no executable recommendation. A successful history response with zero matches is valid and differs from a failed history lookup.

Store the input snapshot hash, exact inputs, component values, total, band, and policy version. The standard-fleet comparison keeps every other fact fixed and changes fleet importance from 20 to 5: score 72, `P2`. Freeze the numeric result outside model output; render it directly in the console.

Use the following sensitivity fixtures to show that all three bands are reachable. Changes in each row are relative to the golden fixture unless stated otherwise:

| Fixture change | Score | Band/outcome |
|---|---|---|
| None | 87 | P1 |
| One prior incident | 81 | P1 |
| Premium fleet | 79 | P2 |
| Voltage 11.6V | 77 | P2 |
| Critical response target 480 minutes | 77 | P2 |
| Standard fleet | 72 | P2 |
| Premium fleet and voltage 10.9V | 89 | P1 |
| Standard fleet and critical response target 60 minutes | 82 | P1 |
| Premium fleet and three prior incidents | 85 | P1 |
| Voltage 10.9V, critical response 60 minutes, three prior incidents | 113 | P1, ceiling |
| Voltage 11.6V, critical response 600 minutes, standard fleet, no prior incidents | 30 | P3 |
| Required evidence missing | null | INSUFFICIENT_CONTEXT; no executable recommendation |

## 7. Skills, evidence, and schemas

Ship a small knowledge pack with the agent:

```text
skills/
  vehicle-triage/
    SKILL.md
    references/signal-catalog.md
  recommendation-authoring/
    SKILL.md
    references/priority-v1.md
    references/action-policy-v1.md
    assets/recommendation.schema.json
  playbook-battery-connectivity/
    SKILL.md
    references/PB-BATTERY-002-v1.md
```

Candidate imports for the Phase 0 compatibility probe are shown below. They are an implementation hypothesis until exercised against the pinned environment; this plan does not record a successful import or skill load:

```python
# Verify these imports and a real skill load against the Phase 0 lockfile.
from google.adk.skills import load_skill_from_dir
from google.adk.tools import skill_toolset
```

ADK's Skills feature is documented as experimental, so skill packaging and loading are part of the compatibility proof. See [ADK Skills](https://adk.dev/skills/). No vector database is required for this corpus. Revisit retrieval architecture if measured catalog size, discovery accuracy, or update requirements justify it; Skill Registry is an option to evaluate, not an automatic replacement for semantic retrieval.

### Evidence contract

Each evidence item has `evidenceId`, entity/document ID, source version or content hash, observation time where relevant, retrieval time, and a typed payload. Playbook citations also carry `playbookId`, version, and section ID. Tool/skill instrumentation records which resources were actually returned or loaded; the model cannot declare that ledger itself.

Recommendation citations must refer to items available to that stage of the run. Validate entity matching, source/version existence, playbook section membership, and action-to-playbook eligibility in code. The model's mention of a loaded playbook alone does not prove semantic support. Evaluate explanation support separately with labeled fixtures and human/offline rubric review.

### Minimum typed schemas

| Schema | Required information |
|---|---|
| Analysis | Demo run, snapshot hash, analysis ID, correlation ID, status, session/invocation references |
| Incident | Vehicle/fleet, selected events, rule version, evidence bundle hash |
| TriageHypothesis | Category, possible causes, uncertainty, supporting evidence IDs, missing evidence |
| PriorityResult | Policy version, source snapshot, components, score, band, status |
| Recommendation | Schema version, incident ID, rationale, evidence references, proposed actions, alternatives |
| ProposedAction | Action type, typed parameters, supporting evidence IDs; no approval or risk authority |
| PersistedAction | Server action ID, immutable recommendation ID/content hash, parameter hash, policy decision/version, dependencies, state |
| Approval | Action binding, reviewer role, request/expiry time, status, reviewer identity, decision receipt |
| Execution | Action ID, idempotency key, input hash, mock result, commit time |
| AuditRecord | Record ID, correlation ID, actor, transition, entity references, server time |

Use strict Pydantic models with forbidden extra fields, bounded lists/text, action enums, and action-specific parameter models. Validate independently at the policy boundary even when the model uses structured output. Unknown evidence IDs, forged approval fields, or mismatched vehicle IDs fail closed.

The server admits one immutable recommendation per incident and assigns its ID and action IDs after validation. Store a canonical content hash: identical resubmission returns the existing record; changed content is a conflict. Schema, policy, and document versions identify immutable definitions; they do not introduce a recommendation revision workflow. MVP recommendations permit at most one action of each type; the diagnostic depends on successful case creation. Editing and superseding a recommendation are deferred to Phase 2.

## 8. Tool and private API surface

Expose these nine read-only MCP tools, with namespaced identifiers normalized to the pinned SDK's naming rules:

| Group | Tools |
|---|---|
| `master` | `get_vehicle_profile`, `get_fleet_profile`, `get_fleet_sla` |
| `events` | `get_recent_vehicle_events`, `get_active_alerts` |
| `twin` | `get_vehicle_operational_state` |
| `knowledge` | `search_prior_incidents`, `get_incident_resolution` |
| `risk` | `get_priority_result` — reads an already persisted result |

All context reads are bound by trusted application code to the current demo run and permitted entities. Do not trust a model-supplied run ID to select another run's records. The operational-state tool derives a small view from the snapshot; a dependency graph is deferred.

The same service exposes private HTTP operations for run/snapshot management, incident persistence, deterministic scoring, recommendation admission and policy evaluation, execution, approval submission/status, run views, and finalization. These are not registered as LLM tools. Audit creation occurs within those handlers, rather than accepting arbitrary model-authored audit records.

Reuse domain names and useful response fields from [services/README.md](services/README.md). The [existing runtime](fleetops_runtime/factory.py) validates requests and returns static examples; it does not persist cases or honor an approval decision as business state. Implement real synthetic handlers and an explicit contract mapping. Record intentional field/enum changes and validate the mapping; do not mistake stub compatibility for working workflow behavior.

## 9. Durable storage and replay

Business state is stored under `demo_runs/{demoRunId}`. The tools service owns the parent run lifecycle. The synth service owns event admissions; trusted domain handlers in the tools service own the remaining records.

| Collection under the run | Owner | Key and durability rule |
|---|---|---|
| `batches` | Synth | Tick/injection operation ID; immutable commit receipt, including malformed-input rejection reasons |
| `events` | Synth | Event ID; create once, conflict on different semantic content; validation status/rejection reason on the record |
| `analyses` | Workflow handler | One analysis per frozen snapshot; session mapping and resume status |
| `incidents` | Correlation handler | Stable vehicle/rule/run hash |
| `evidence` | Context handler | Content/version-derived ID; immutable snapshots |
| `recommendations` | Policy handler | Incident ID; one immutable admitted recommendation and its content hash |
| `actions` | Policy/execution handler | Server action ID; versioned state transitions |
| `cases` | Case handler | Incident-derived case ID; at most one case per incident |
| `approvals` | Approval handler | Action ID; immutable content binding and atomic terminal decision |
| `executions` | Execution handler | Stable action idempotency key; committed input/result |
| `audit` | All trusted handlers | Entity/transition/version ID; append-only through application APIs |

Managed runtime sessions/checkpoints store orchestration progress. Firestore business records store approvals and effects. Persist the mapping between them; neither a Streamlit session variable nor an in-memory Python object is authoritative.

For each mock execution, first authenticate the caller and verify its access to the action. A Firestore transaction checks the execution key: an existing receipt with the same input hash returns the original result, even if approval has since expired; a different input hash is rejected. If no receipt exists, the transaction checks current run/action state, policy, dependencies, and approval if needed, then creates the mock effect, execution receipt, action transition, and audit record together. Returning an existing receipt performs no new effect. Firestore transaction callbacks must not make network calls or invoke the model.

Idempotency keys include demo run, incident, and action type. One admitted recommendation and at most one action of each type per incident make that key sufficient for MVP scope. The case also has incident-level uniqueness. Store normalized parameters and the immutable recommendation hash; changed content cannot reuse an action or execution key. A later revision feature must explicitly redesign these bindings before it is implemented.

These guarantees apply to mock effects stored in the same database transaction. Real external commands would require an outbox/reconciliation design and downstream idempotency; that is outside MVP scope.

Audit export to Cloud Logging is supplementary. A failed log export does not remove the persisted transition. If a required business audit transaction fails, the effect must not commit. Terminal failure and no-incident paths also produce records.

## 10. Policy and human approval

### Authoritative policy `action-policy-v1`

| Action | Derived risk | Decision | Execution |
|---|---|---|---|
| `create_service_case` | LOW | Allowed after valid evidence/recommendation | Transaction creates synthetic case |
| `remote_diagnostic` | MEDIUM | Requires `fleet_ops_manager` approval and successful case creation | Transaction writes mock diagnostic result |
| `customer_notification` | MEDIUM | Blocked in MVP | No executor registered |
| `firmware_action` | HIGH | Blocked | No executor registered |
| Any other type | Unsupported | Reject invalid recommendation | No executor registered |

Known blocked actions can coexist with valid allowed actions, but are individually recorded as blocked. Invalid schema, unsupported action types, entity mismatch, or invalid evidence rejects the recommendation before any action executes. Fleet escalation adds a visible escalation flag/reason for strategic-fleet critical connectivity; it does not override a block or grant approval. Additional action types require a deliberate policy/schema revision and tests.

`action-policy-v1` is a version-stamped, pure in-process Python module packaged with the tools service. It performs no I/O: no network, skill/reference loading, database access, environment lookup, or wall-clock lookup. Skill policy references explain the rules but are never executable policy sources. Pass trusted records, the run's pinned policy version, and an explicit server-time value to the module; persistence handlers own transactional reads/writes.

The service calls this module when admitting a recommendation and again inside the execution transaction using the records read there. The transaction attempt receives server time from its wrapper; if Firestore retries the callback, the wrapper refreshes that value before calling the pure policy function. No external API calls are made in the callback. If the run's pinned policy version is unsupported or mismatched, fail closed with `POLICY_VERSION_MISMATCH` and finish as `NEEDS_REVIEW`; do not mutate the pending recommendation. Policy hot reload, approval migration, and supersession are Phase 2 work.

### Action state transitions

```text
PROPOSED -> BLOCKED
PROPOSED -> READY -> EXECUTED
PROPOSED -> PENDING_APPROVAL -> APPROVED -> EXECUTED
                           -> REJECTED
                           -> EXPIRED
APPROVED -> EXPIRED if its authorization expires before execution
READY / APPROVED -> FAILED when validation/dependency checks fail
```

Reserve the `SUPERSEDED` status code for Phase 2, but do not implement transitions into it, revision endpoints, revision UI, or supersession tests in the MVP.

Transport failures with an unknown result are resolved by querying the execution receipt and retrying the same key. They are not treated as permission to create a new action. Model retries never run after entering approval or execution just to recreate lost state.

### Approval binding and identity

Each request binds `demoRunId`, incident, action ID/type, normalized parameter hash, immutable recommendation ID/content hash, evidence bundle hash, policy version, required reviewer role, and absolute expiry in server UTC.

At run creation, copy the validated deployment setting `APPROVAL_TTL_SECONDS` into immutable `approvalTtlSeconds` on the run. Default to 7,200 seconds; a recording/restart-proof run can explicitly use 28,800 seconds. Bound the configured duration to 60–86,400 seconds and show the selected duration and absolute approval expiry in the console. Each request copies the run's duration and sets `expiresAt = requestedAt + approvalTtlSeconds`. Later configuration changes do not extend existing runs or approvals, and model/browser decision payloads cannot change expiry. Offline expiry tests use an injected server clock instead of waiting in real time.

Deploy the console behind an authenticated access layer such as IAP. The console validates the signed identity assertion and maps its verified subject to a small server-controlled reviewer allowlist. It submits the decision through its own service identity; the tools service accepts reviewer assertions only through this trusted backend path. No browser-supplied role, plain email header, or model text establishes reviewer identity. Phase 0 must test the full identity chain and denial path. A local test identity is permitted only in a local configuration that deployment rejects.

Approval submission transactionally checks that the request is still pending, unexpired, bound to current content/policy, and assigned to a role the verified reviewer holds. It stores one decision and one audit record. Repeating the same decision returns the existing receipt; a conflicting second decision returns a conflict. Rejected/expired requests cannot execute.

There is no recommendation edit or replacement path in the MVP. Reject submissions that change the admitted content or any approval binding. To exercise a different recommendation, create a separate demo run. Approval never transfers between runs. Phase 2 may add revision and supersession only alongside a concrete editing use case.

Commit the approval before sending the runtime resume signal. The resume payload is a decision receipt reference, not an authoritative `approved=true` flag. Orchestration reads and verifies the stored decision. If signaling fails, the console can retry from the persisted receipt. Expiry is checked at decision and execution time and refreshed when viewing pending actions; it does not require a continuously running scheduler.

## 11. Workflow and failure behavior

The following is algorithmic pseudocode, not a claim about exact SDK signatures. Phase 0 supplies the executable ADK wrapper, human-input response schema, checkpoint configuration, and resume request format.

```text
load or create analysis for frozen snapshot
correlate snapshot
if NO_INCIDENT: audit outcome and finish without a model
if MULTIPLE_CANDIDATES: record candidate IDs, report unsupported batch, finish without a model
gather required context and persist evidence
if context unavailable: persist NEEDS_REVIEW and finish without execution
run Triage with read-only tools; persist validated hypothesis
score trusted snapshot deterministically; persist result
run Recommendation with read-only tools and frozen score/evidence
admit recommendation through authoritative policy API
persist individual action decisions and audit records
execute READY case action transactionally
if case failed: leave dependent diagnostic unexecuted and report failure
if diagnostic needs approval:
    persist approval request and pending action
    pause with approval ID and evidence/action card
    on resume: fetch persisted decision receipt and verify binding
    if approved: recheck policy, expiry, dependency; execute once
    if rejected/expired: record outcome without execution
finalize from persisted per-action results and audit links
```

Use stable node/subrun identifiers derived from analysis ID and step name; there is one immutable recommendation per incident. Resume must reuse frozen inputs and persisted outputs. Protect analysis start with a transactional ownership/lease mechanism so duplicate console requests reconnect rather than launch concurrent processing. Record and handle the interruption IDs required by the selected ADK version.

For transient read failures, allow at most two retries with backoff; then produce `NEEDS_REVIEW` with the missing dependency. Do not substitute plausible generated facts. Permit one bounded schema-repair attempt before admission; if output remains invalid, finish with `INVALID_RECOMMENDATION` and zero effects. Freeze successful LLM outputs before downstream mutations. Dependency failures, permission denials, and validation failures must appear in the console.

The demo run moves from `OPEN` to `CLOSED` when its snapshot is frozen. Its analysis then moves from `CREATED` to `ANALYZING`. Analysis outcome/status values include `NO_INCIDENT`, terminal `MULTIPLE_CANDIDATES`, `NEEDS_REVIEW`, `INVALID_RECOMMENDATION`, `PENDING_APPROVAL`, `COMPLETED`, `COMPLETED_WITH_REJECTION`, `COMPLETED_WITH_BLOCKS`, and `FAILED`. The presence of a created case does not imply that the pending diagnostic succeeded. Expired approvals leave an explicit reason and move the analysis to `NEEDS_REVIEW`; the MVP offers no edit or retry-with-new-content path from that outcome.

## 12. Deployment artifacts and authentication

Implement these artifacts during the build; the paths below are planned, not existing commands to run today:

| Artifact | Purpose |
|---|---|
| `synth/` | Seeded catalog and batch-injection FastAPI app |
| `mcp/` | Read-only MCP endpoint plus private workflow API and Firestore repositories |
| `fleetops_control_agent/` | ADK graph, tool subsets, typed outputs, packaged skills |
| `console/` | Authenticated Streamlit app, evidence cards, create/analyze/status and approve/reject; no recommendation editing or candidate selection |
| `schemas/` | Versioned JSON schemas and mapping notes |
| `fixtures/` | Golden/noise/error inputs and expected deterministic outcomes |
| `evals/` | LLM behavior fixtures and explanation rubrics |
| `scripts/bootstrap.ps1` | Enable needed APIs, provision resources, identities, IAM, and indexes |
| `scripts/deploy.ps1` | Deploy pinned builds and verified runtime/console configuration |
| `scripts/demo.ps1` | Create run, inject, analyze, print console/trace references |
| `scripts/teardown.ps1` | Remove only resources recorded for this dedicated demo deployment |

Use PowerShell scripts for this workspace, with optional Bash equivalents later. Every cloud command explicitly selects the project and location. Include runtime deployment config and environment propagation in source control without credentials. Record agent resource/session identifiers as generated deployment/run outputs.

Bootstrap must account for the chosen deployment path's build, Artifact Registry, service usage, IAM/service-account attachment, Firestore, Cloud Run, runtime invocation, and observability permissions. Distinguish the deploying principal, build identity, synth service, tools service, console service, and agent runtime identity. Service invocation permission alone does not authorize private application operations.

### MCP credentials

- Configure `MCP_ENDPOINT_URL` as the actual transport route, for example `https://service.run.app/mcp`.
- Configure `MCP_AUDIENCE` separately as the Cloud Run service audience. Do not assume the transport path belongs in the audience.
- Use the pinned SDK's refresh-capable auth provider/header callback. Reuse cached credentials only while valid; refresh before expiry and on reconnect/resume. Never bake a fetched bearer token into module-level tool construction.
- Start with an explicit 30-second MCP connection timeout; measure cold starts and tune it. Limit retries and distinguish handshake time from overall model/workflow latency.
- Prefer the Agent Identity path if Phase 0 proves it. Google's guidance distinguishes Agent Identity from an attached service account for Cloud Run ID tokens and describes service-account impersonation when needed. Provision that path explicitly, or document an attached service account as the chosen MVP identity; do not silently assume `fetch_id_token()` behaves identically for both. See [Google Cloud Run authentication guidance](https://googlecloudplatform.github.io/iam-federation-tools/adk-cloudrun/).

Keep the tools and synth services private. The console's authenticated access layer must be configured and tested before a deployed reviewer can perform actions. Do not publish an unauthenticated approval console as the default deployment.

## 13. Tests, evaluation, and observability

Deterministic unit/integration tests are the release authority for policy, storage, and scoring. `adk eval` or a model judge can evaluate agent behavior where supported by the pinned SDK; neither substitutes for transactional integration tests. Add CI for these checks in the MVP, regardless of whether Cloud Build is used.

| Test | Required outcome |
|---|---|
| Golden approval | Score 87/P1; case exists before pause; one diagnostic after approval |
| Golden rejection | Case remains; zero diagnostics; rejection audited |
| Benign ambient batch | NO_INCIDENT, zero model calls, zero actions |
| Correlation boundaries | 12-minute inclusive window, voltage boundary, sorted out-of-order input, duplicate IDs, and rejection reasons behave as specified |
| Multiple-candidate guard | Constructed batch returns terminal MULTIPLE_CANDIDATES with candidate IDs, zero LLM calls, zero effects; no selection-flow test |
| Unknown vehicle / missing SLA / failed history read | Typed error or NEEDS_REVIEW; no fabricated evidence or execution |
| Priority fixtures | Section 6 sensitivity table and boundary values match, including 113 ceiling and 30/P3; model confidence changes do not affect score |
| Known prohibited / unknown action | Known actions blocked individually; unknown type invalidates recommendation |
| Injection in event or retrieved text | Cannot add tools, change numeric score, authorize actions, or fabricate approval |
| Direct tool/API bypass attempt | Model tool registry has no mutations; runtime identity cannot submit reviewer decisions; executor rejects missing authorization |
| Duplicate/concurrent approval | One terminal decision, one effect; conflicting decision rejected |
| Expiry configuration and content tampering | Run-pinned TTL and server clock govern expiry; later settings do not extend it; changed action/content/evidence binding is rejected; no revision workflow |
| Restart and resume | Persisted pending action recovered; prior case creation not repeated |
| Commit succeeds but response is lost | Same key returns original effect/receipt; no duplicate case/diagnostic |
| Approval commits but resume signal fails | Retry receipt-based resume without a second decision/effect |
| Authentication expiry/reconnect | Fresh authorized MCP request works; unauthorized reviewer denied |
| Skill/evidence grounding | Claimed sources were available with correct IDs/versions/sections; unsupported explanation fails the rubric |
| Schema repair and dependency outage | Bounded retries; visible terminal/review state; no hidden execution |
| Two demo runs and cleanup | No state/approval leakage; cleanup cannot affect an active or unrelated run |

Run deterministic tests offline using the Firestore emulator where needed. Pin seed, demo clock, snapshot, schemas, and policy versions. Run live-model evals separately with recorded configuration and at least five golden repetitions; publish semantic pass counts, schema-repair frequency, and costs. The initial golden release criterion is 5/5 valid, evidence-backed action sets and zero control violations. A single hard control failure blocks release; free-text scores are explanatory evidence, not a safety verdict.

Carry `demoRunId`, `analysisId`, `incidentId`, `correlationId`, action ID, and immutable recommendation ID/hash through relevant records/spans. Capture tool names, sanitized input/output references, model/version, token counts, latency, policy result, reviewer decision, and execution receipt. Do not log bearer tokens or private reasoning traces. Record concise rationales and evidence.

Publish measured requests/tokens per incident, pre-approval decision latency, post-approval execution latency, approval waiting time, grounding pass rate, and duplicates suppressed. Report p95 only with sample count and measurement boundaries; exclude human waiting time from decision latency. Separate warm and cold runs. Verify actual deployed spans instead of assuming one tracing flag covers custom service code.

## 14. Build phases and exit criteria

| Phase | Deliverable | Done when | Planning estimate |
|---|---|---|---|
| 0 | Platform/auth/resume proof and exact dependency lock | Minimal durable graph first; all Section 3 checks pass or a documented orchestration revision is made | 3–4 days |
| 1 | Schemas, fixture catalog, run/snapshot storage, generator | Golden/noise batches reproducible; duplicate, rejection, closure, TTL configuration, and score sensitivity fixtures tested | 3 days |
| 2 | Private workflow API, nine read-only MCP tools, domain repositories | Permissions and contract mappings tested; repository primitives persist records in emulator/cloud | 3 days |
| 3 | Deterministic workflow including pure policy, approval, mock execution | Transactional cross-record invariants and full approve/reject/retry/expiry flow work with fixed model-output fixtures and zero model calls | 5–6 days |
| 4 | Knowledge pack and two LLM stages | Structured evidence-backed outputs pass golden and missing-context evals | 3 days |
| 5 | Authenticated console and integrated deployment | Case-before-pause, IAP identity/denial, restart/resume, reject and configured-expiry paths verified; no revision/selection UI | 3–4 days |
| 6 | Regression suite, live evals, trace evidence | Cross-component failure/concurrency cases pass; model results and proof artifacts recorded in CI | 3–4 days |
| 7 | Demo recording, README, cleanup verification | Five-minute walkthrough and resource-scoped teardown documented and exercised | 2–3 days |

**Planning estimate: 25–30 working days for one implementer, provisional until Phase 0.** These bounds are the sum of the phase estimates, assuming project access is available and excluding external approval delays. The trims remove unused flows but leave substantial persistence, authentication, and failure-handling work. Phase 3 explicitly includes transaction design and emulator integration tests; Phase 6 integrates and broadens checks already built alongside each component. Re-estimate from the platform proof. Deployment begins in Phase 0 and is exercised throughout; it is not postponed to the final week.

Phase 3 is the application checkpoint: the complete governed business flow must work with zero model calls before adding model reasoning. Phase 0 may use a minimal model call solely to test SDK/platform compatibility.

## 15. Five-minute demo and completion definition

1. Show the synthetic-data label, seed/policy versions, authenticated reviewer, and run-pinned approval duration. Use an explicit longer duration for a recording or restart proof if needed.
2. Analyze a noise-only run: no incident, no model invocation, no case.
3. Start a fresh golden run: show the selected three signals, source evidence, and reproducible score 87.
4. Show the hypothesis and recommendation. Open the created case while the diagnostic remains pending.
5. Reconnect to the pending run from a fresh client. Present the separate worker-restart proof artifact, or demonstrate it live if supported; do not equate client reconnection with worker recovery.
6. Approve, then repeat the same submission: show one diagnostic receipt. In a separate prepared run, reject and show zero diagnostic effects.
7. Follow the correlation ID through evidence, policy, reviewer, and action records. Show the regression results for blocked actions and bypass attempts.

MVP completion requires the deployed golden approval/rejection paths, the offline deterministic suite, recorded platform proof, reviewer authorization, bounded retries, exact score fixtures, and traceable effects. Describe the project as demonstrating production-oriented control patterns with synthetic data; do not claim production readiness or operational diagnostic accuracy.

## 16. Cost, cleanup, and remaining risks

Set explicit maximum instance counts and model request/token limits appropriate to a private demo. Start with zero minimum instances where supported; warm a service temporarily for a presentation only when measurements justify it. Cloud Scheduler is not provisioned in this MVP. Budget for model use, runtime/session storage and operations, Firestore, builds/images, staging storage, and logs. Free-tier eligibility and current pricing must be checked for the actual project; idle cost is not a fixed guarantee.

`teardown.ps1` reads a deployment manifest with the project and exact created resource IDs. It supports a dry run, checks ownership labels, and removes the agent, three Cloud Run services, dedicated access/IAM resources, demo documents including subcollections, and dedicated staging/build artifacts. Never clear a shared project database or bucket. Refuse cleanup while an analysis is executing or an approval is pending or approved-but-unexecuted. Finish/reject the demo or reconcile an expired/failed run to a terminal outcome before cleanup. No supersession or cancellation workflow is required for teardown; cleanup removes only selected terminal run/deployment resources.

| Remaining risk | Planned resolution |
|---|---|
| SDK/runtime compatibility and native checkpoint durability | Phase 0 evidence with exact versions; no unsupported durability claim |
| Cloud Run/Agent Identity integration | Prove token audience, refresh, impersonation if needed, and IAM separately |
| Reviewer identity forwarding | Test signed identity validation and backend caller restrictions |
| Model inconsistency or unsupported explanations | Frozen evidence, schema validation, bounded repair, repeated evals |
| Concurrent requests and partial failures | Transactional receipts, business uniqueness keys, approval-before-resume protocol |
| Policy or code changes during a pending run | Pin pure module version per run; avoid redeployment while pending; mismatched versions fail closed to NEEDS_REVIEW |
| Scope growth | One rule, one main playbook, two model stages, two mock executable action types |

## 17. Revision record

This revision separates read tools from private mutation APIs; makes policy authoritative at execution; specifies per-action approval and case-before-pause behavior; adds durable business state and transactional idempotency; defines correlation, clock, scoring, and missing-data rules; strengthens Phase 0; corrects skill imports and token handling; adds authenticated reviewers; reduces model stages; and expands acceptance coverage for rejection, replay, outages, and grounding. Existing source plans are kept for comparison; later edits only add pointers to this plan and correct stale details.

The scope-review update defers recommendation revisions/supersession and candidate selection, retains their status contracts without implementing unused flows, replaces the quarantine collection with rejection fields, expands the illustrative score ceiling to 113 while preserving golden 87/P1, pins policy as pure in-process code, records configurable approval TTL per run, marks skill imports as untested against the eventual lockfile, and re-baselines the build to 25–30 working days. The next implementation task is the minimal Phase 0 worker-recovery proof.
