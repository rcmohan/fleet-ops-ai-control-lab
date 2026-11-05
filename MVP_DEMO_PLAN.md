# FleetOps AI Control Lab — MVP Demo Implementation Plan

> **Superseded:** [`MVP-DEMO-UPDATED.md`](MVP-DEMO-UPDATED.md) is the proposed source of truth for MVP scope. This plan is kept for comparison; its estimates, model notes, and dates are as of 2026-09-05.

**Status:** Superseded | **Date:** 2026-09-05 | **Target:** one governed incident, end to end, running on Google Cloud

This plan turns the concept in [`AGENTIC.md`](AGENTIC.md) into a buildable MVP that actually runs on **Gemini Enterprise Agent Platform** (Agent Runtime + ADK), backed by synthetic data served from Cloud Run.

It answers three questions:

1. What is the smallest thing that genuinely runs on Google's Agent Platform?
2. How is the synthetic data produced and served?
3. Which agents actually need an LLM — and which must not have one?

---

## 1. Scope: one flow, done properly

Build **exactly one** demo narrative and make it excellent.

> A NovaFleet vehicle on a strategic-tier fleet emits low battery voltage, then a missed heartbeat, then a failed remote diagnostic within a 12-minute window. The system correlates the three signals into one incident, forms a cause hypothesis, retrieves fleet SLA + playbook + prior incidents, scores priority deterministically, recommends an action, blocks the restricted part of that action at a policy gate, pauses for a human, resumes on approval, executes only the allow-listed action, and writes a complete audit trail.

Everything else in `AGENTIC.md` and `OVERVIEW.md` is Phase 2+.

**Explicitly out of scope for the MVP:** Pub/Sub streaming, Vector Search / pgvector, BigQuery analytics, the 15-service Postgres estate, multi-region, auth beyond service identity, a React UI.

### The golden scenario

Deterministic and fixed, so evals and demos are reproducible:

| Field | Value |
|---|---|
| Vehicle | `veh_10482` (Aster MetroVan 250, 2022) |
| Fleet | `flt_204` — customer tier `strategic`, SLA critical 2h / high 8h |
| Region | `us-southeast` |
| Signals | `LOW_BATTERY_VOLTAGE` (11.4V) → `MISSED_HEARTBEAT` → `REMOTE_DIAGNOSTIC_FAILED` |
| Expected priority | `P1`, score 87 |
| Expected recommendation | create service case **+** request approval for remote diagnostic |
| Expected gate result | `create_service_case` allowed; `remote_diagnostic` requires approval; `customer_notification` blocked |

> **ID convention:** use the repository's existing `veh_` / `flt_` / `tcu_` / `sp_` / `mtn_` prefixes from [`docs/architecture/master-data-services.md`](docs/architecture/master-data-services.md), not the `VH-` / `FL-` forms used in earlier drafts.

---

## 2. Target deployment

```text
Cloud Scheduler (paused by default; manual trigger for demos)
        |
        v
fleetops-synth-fn ....................... Cloud Run function (Python)
  - deterministic seeded master-data generator (no database)
  - scenario injector: writes the golden 3-signal cluster
  - appends events to Firestore, collection: events/
        |
        v
fleetops-tools-mcp ...................... Cloud Run service (streamable HTTP MCP)
  - reads Firestore + calls the seeded generator
  - ~17 typed tools (context, scoring, policy, actions, audit)
  - deterministic; unit-tested; no LLM
        |
        v
fleetops-control-agent .................. Agent Runtime (reasoningEngine)
  ADK graph Workflow, one deployment:
    ingest -> correlate -> TRIAGE(LLM) -> context fan-out
      -> score -> explain(LLM) -> RECOMMEND(LLM)
      -> policy gate -> [RequestInput: HITL pause] -> execute -> audit
        |
        v
fleetops-console ........................ Cloud Run service (Streamlit)
  - streams the agent run, renders evidence, collects approve/reject
  - resumes the paused workflow
        |
        v
Cloud Trace + Cloud Logging  (adk deploy --trace_to_cloud)
```

Four deployables. That is the whole MVP.

| Layer | Product | Why this and not the alternative |
|---|---|---|
| Agent runtime | Agent Runtime (`reasoningEngine`) | The point of the exercise. Managed sessions + HITL resume + tracing. |
| Agent framework | ADK 2.5 (Python) | Graph Workflows, Skills, resumable HITL, MCP client — all needed here. |
| Synthetic data | Cloud Run function | Cheap, stateless, scales to zero, trivially re-seedable. |
| Event log | Firestore (Native) | Free tier, no schema migration, good enough for an append-only event log. |
| Tools | Cloud Run service speaking MCP | Real agent-safe boundary; the architecture story. |
| Knowledge | **ADK Skills** (SKILL.md packages) | Replaces a vector DB at MVP scale; Skill Registry is the documented scale path. |
| UI | Streamlit on Cloud Run | Fastest path to a credible HITL screen. |
| Observability | Cloud Trace / Logging via OTel | One flag on deploy. |

**Deliberately deferred:** Postgres per service, Pub/Sub, Vector Search, BigQuery. Each is a Phase-2 upgrade with an obvious insertion point, and none is needed to prove the architecture.

---

## 3. Which components actually need an LLM

This is the most important design decision in the project, and the original `AGENTIC.md` did not state it. Most of the pipeline should be deterministic. An LLM belongs only where the task has genuine ambiguity that rules cannot resolve.

| # | Component | LLM? | Model | Rationale |
|---|---|---|---|---|
| 1 | Event ingest / normalize | **No** | — | Schema validation and dedupe. Pure code. |
| 2 | **A. Signal Monitor / correlation** | **No** | — | Sliding-window correlation over an event log is a rules job. An LLM here is slower, costlier, non-reproducible, and fails regression evals. |
| 3 | **B. Health Triage** | **Yes** | `gemini-3.5-flash` | Genuine ambiguity: map a messy, partial, sometimes-conflicting multi-signal pattern to a cause hypothesis, and decide what context is still missing. This is the reasoning core. |
| 4 | Context retrieval fan-out | **No** | — | Parallel typed tool calls. An LLM adds latency and a hallucination surface for zero benefit. |
| 5 | **C. Priority scoring** | **No** | — | Weighted arithmetic. Must be reproducible, auditable, and unit-testable. A score a model can drift on is not a control. |
| 5b | Priority *explanation* | Yes (narrow) | `gemini-3.5-flash` | Narrates the already-computed components into prose. Structurally forbidden from changing the number. |
| 6 | **D. Recommendation** | **Yes** | `gemini-3.5-flash` | Real synthesis: playbook + prior resolutions + live context into action, rationale, alternatives, tradeoffs. Constrained by a response schema. |
| 6b | Communication draft | Yes (gated) | `gemini-3.5-flash` | Free text, therefore always behind approval. Never auto-sent. |
| 7 | **E. Policy Gate** | **No — never** | — | It is a security control. An LLM gate is prompt-injectable by its own inputs, and those inputs include model-generated text. Deterministic schema + allowlist + risk-tier matrix. |
| 8 | Bounded execution | **No** | — | Allowlist dispatch with idempotency keys. |
| 9 | Audit | **No** | — | Append-only writes. |
| 10 | Eval judge | Yes (offline) | `gemini-3.5-flash` | Grading rubric adherence in CI. Never in the request path. |

### Net result

**Two of the five agents need an LLM** (Triage, Recommendation), plus one narrow narration step and one gated drafting step. **Four LLM calls per incident**, roughly 2–4s of model latency total.

That ratio *is* the portfolio argument: an operations control plane where the model reasons and the system decides.

**Model notes.** `gemini-3.5-flash` is the model used in the Agent Runtime ADK quickstart and is the safe default. `gemini-3.6-flash` is the newer workhorse and a drop-in candidate — benchmark both against the eval set before switching. Avoid the `gemini-2.5-*` family: it shuts down on the Agent Platform Gemini API on **2026-10-20**.

---

## 4. The synthetic data plane

### 4.1 Deterministic seeded generation — no master-data database

Master data is a **pure function of the entity ID**. `generate_vehicle("veh_10482")` derives make, model, year, fleet, region, odometer, and service tier from a seeded PRNG keyed on `sha256(SEED + vehicle_id)`.

This buys a lot:

- No Postgres, no migrations, no seeding job for the MVP.
- Any vehicle ID resolves instantly — the demo never hits a missing record.
- The same ID yields the same facts in local tests, CI, and production. Evals are stable.
- Phase 2 swaps the generator for the real per-service Postgres estate behind the same tool interface.

```python
# synth/master.py
import hashlib, random

SEED = "novafleet-v1"

def _rng(*parts: str) -> random.Random:
    h = hashlib.sha256((SEED + "|" + "|".join(parts)).encode()).digest()
    return random.Random(int.from_bytes(h[:8], "big"))

def generate_vehicle(vehicle_id: str) -> dict:
    r = _rng("vehicle", vehicle_id)
    return {
        "vehicleId": vehicle_id,
        "make": r.choice(["Aster", "Kessel", "Voyant"]),
        "model": r.choice(["MetroVan 250", "HaulLine 400", "CityLink 120"]),
        "modelYear": r.randint(2019, 2025),
        "fleetId": f"flt_{r.randint(200, 219)}",
        "regionCode": r.choice(REGIONS),
        "telematicsUnitId": f"tcu_{r.randint(80000, 89999)}",
        "serviceTier": r.choice(["standard", "premium", "premium"]),
        "odometerKm": r.randint(20_000, 240_000),
        "lifecycleStatus": "in_service",
        "synthetic": True,
    }
```

A small `OVERRIDES` dict pins the golden-scenario entities (`veh_10482`, `flt_204`) so the demo is fixed while everything else stays generated.

### 4.2 `fleetops-synth-fn` — the Cloud Run function

One Python Cloud Run function, three routes:

| Route | Purpose |
|---|---|
| `POST /tick` | Emit one batch of ambient telemetry across ~100 vehicles. Idempotent per `tick_id`. |
| `POST /scenario/{name}` | Inject a named scripted pattern. `battery_connectivity` writes the golden 3-signal cluster on `veh_10482` with correct relative timestamps. |
| `POST /reset` | Clear the Firestore event log and reset the demo clock. |

Ambient noise is what makes the correlation step non-trivial and the demo honest: normal driving, GPS drift, isolated harsh braking, duplicate event IDs, and deliberately out-of-order timestamps.

Events are appended to Firestore `events/{eventId}`:

```json
{
  "eventId": "evt_...", "vehicleId": "veh_10482",
  "eventType": "LOW_BATTERY_VOLTAGE", "severity": "warning",
  "observedAt": "2026-09-05T18:40:00Z", "ingestedAt": "2026-09-05T18:40:03Z",
  "regionCode": "us-southeast", "payload": {"voltage": 11.4},
  "synthetic": true
}
```

Index on `(vehicleId, observedAt desc)` and `(regionCode, observedAt desc)`.

**Scheduler is paused by default.** Trigger `/tick` manually or from the console UI. A demo project that quietly bills for a cron job is a bad portfolio artifact.

---

## 5. Skills, Tools, and Services — three distinct layers

The original `AGENTIC.md` used "skill" to mean both a knowledge package and a callable function. ADK 2.5 gives these separate meanings, and the project should adopt them.

| Layer | ADK concept | Contains | Example |
|---|---|---|---|
| **Skill** | `models.Skill` / `SKILL.md` in a `SkillToolset` | Instructions, references, schemas, scripts. Procedural *knowledge*, progressively disclosed. | *How to interpret a power/connectivity signal cluster* |
| **Tool** | `McpToolset` over streamable HTTP | A typed, side-effect-bounded call | `get_fleet_sla(fleet_id)` |
| **Service** | Cloud Run | The synthetic implementation behind the tool | `fleetops-tools-mcp` calling `fleetops-synth-fn` |

**Rule:** agents hold no fleet facts. Skills say *how to reason*; tools return *what is true*.

### 5.1 Skill pack (ships with the agent)

```text
skills/
  vehicle-triage/
    SKILL.md                     # how to form a cause hypothesis from a cluster
    references/dtc-catalog.md
    references/severity-matrix.md
  fleet-priority/
    SKILL.md                     # how the score is composed and how to explain it
    references/scoring-model.md
  recommendation-authoring/
    SKILL.md                     # how to write an evidence-backed recommendation
    assets/recommendation.schema.json
    references/action-catalog.md
  playbook-battery-connectivity/ # PB-BATTERY-002
    SKILL.md
  playbook-safety-escalation/    # PB-SAFETY-001
    SKILL.md
  playbook-firmware-rollback/    # PB-FW-003
    SKILL.md
```

```python
from google.adk.skills import skill_toolset

fleet_skills = skill_toolset.SkillToolset(skills=[...])  # exposes load_skill,
                                                         # load_skill_resource,
                                                         # run_skill_script
```

Skill frontmatter requires a lowercase kebab-case `name` (<= 64 chars) and a non-empty `description` (<= 1024 chars). The description is what the agent matches against when deciding which skill to load, so write it as a retrieval query, not a title.

### 5.2 Playbooks as Skills instead of a vector database

Five playbooks do not need Vector Search. Ship each as a Skill; `SkillToolset` already does discovery-by-description and on-demand loading, which is retrieval with citations built in — the agent names the playbook it loaded, so grounding is verifiable for free.

The scale path is documented and clean: move the pack to the **Google Cloud Skill Registry** when the catalog reaches hundreds of playbooks. Say that in the write-up; "I chose not to add a vector database, and here is the threshold at which I would" is a stronger signal than adding one.

### 5.3 MCP tool surface (consolidated)

`AGENTIC.md` originally proposed six MCP servers. For the MVP that is six deployables, six cold starts, and six failure modes for one demo. Ship **one** MCP service exposing the six logical tool groups as namespaced tools; split later if a group needs independent scaling.

| Group | Tools |
|---|---|
| `master` | `get_vehicle_profile`, `get_fleet_profile`, `get_fleet_sla` |
| `events` | `get_recent_vehicle_events`, `get_active_alerts`, `detect_event_cluster` |
| `twin` | `get_vehicle_operational_state`, `get_downstream_impact` |
| `knowledge` | `search_prior_incidents`, `get_incident_resolution` |
| `risk` | `calculate_priority_score`, `get_action_eligibility`, `validate_recommendation` |
| `actions` | `create_service_case`, `request_human_approval`, `record_approval_decision`, `write_audit_event` |

The 15 FastAPI contracts already in [`services/`](services/) are the specification for these tools. The MCP service is a thin adapter over that contract surface, so nothing already built is discarded — but only one container is deployed for the MVP.

Two client-side notes that will otherwise cost an afternoon each:

- ADK's default MCP connection timeout is ~5s, shorter than a Cloud Run cold-start handshake. **Set it explicitly** (30s).
- Cloud Run requires an ID token; mint one with `google.oauth2.id_token.fetch_id_token()` and pass it as an `Authorization` header in `StreamableHTTPConnectionParams`. Do not append `/mcp` or `/sse` to the configured URL.

```python
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

fleet_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=MCP_URL,
        headers={"Authorization": f"Bearer {fetch_id_token(Request(), MCP_URL)}"},
        timeout=30,
    )
)
```

---

## 6. The agent: one ADK graph Workflow

One `reasoningEngine`, one root `Workflow`. Deterministic nodes are `@node` functions; only two nodes are `LlmAgent`s.

```python
# fleetops_control_agent/agent.py
from google.adk.workflow import Workflow, node, Context, RequestInput
from google.adk.agents import LlmAgent

MODEL = "gemini-3.5-flash"

triage_agent = LlmAgent(
    name="triage",
    model=MODEL,
    instruction=TRIAGE_INSTRUCTION,          # loads the vehicle-triage skill
    tools=[fleet_skills, fleet_tools],
    output_schema=TriageHypothesis,
    output_key="triage",
)

recommend_agent = LlmAgent(
    name="recommend",
    model=MODEL,
    instruction=RECOMMEND_INSTRUCTION,
    tools=[fleet_skills, fleet_tools],
    output_schema=Recommendation,            # structured output, re-validated downstream
    output_key="recommendation",
)

@node()                                       # no LLM
async def correlate(ctx: Context, node_input: dict) -> dict:
    """Sliding-window signal correlation -> incident candidate."""

@node()                                       # no LLM
async def score_priority(ctx: Context, node_input: dict) -> dict:
    """Deterministic weighted score -> P1/P2/P3 + components."""

@node()                                       # no LLM, and never one
async def policy_gate(ctx: Context, node_input: dict) -> dict:
    """Schema validation + action allowlist + risk tier + approval matrix."""

@node(rerun_on_resume=False)
async def human_approval(ctx: Context, node_input: dict):
    yield RequestInput(message=render_approval_card(node_input))

@node(rerun_on_resume=True)
async def fleetops_workflow(ctx: Context, event_batch: dict) -> dict:
    incident   = await ctx.run_node(correlate, node_input=event_batch,
                                    run_id=f"corr-{incident_id}")
    hypothesis = await ctx.run_node(triage_agent, node_input=incident)
    context    = await ctx.run_node(gather_context, node_input=hypothesis)
    scored     = await ctx.run_node(score_priority, node_input=context)
    narrated   = await ctx.run_node(explain_priority, node_input=scored)
    rec        = await ctx.run_node(recommend_agent, node_input=narrated)
    decision   = await ctx.run_node(policy_gate, node_input=rec)

    if decision["requiresHumanApproval"]:
        approval = await ctx.run_node(human_approval, node_input=decision)
        decision = await ctx.run_node(record_decision, node_input=approval)

    executed = await ctx.run_node(execute_bounded, node_input=decision)
    return await ctx.run_node(write_audit, node_input=executed)

root_agent = Workflow(name="fleetops_control", edges=[("START", fleetops_workflow)])
```

### Why the graph Workflow and not `SequentialAgent`

`RequestInput` gives a **real** pause: the run halts, Agent Runtime persists the checkpoint, the process can die, and an approval hours later resumes from the exact node with already-completed sub-nodes skipped. That is a true HITL control, not a `{"status": "PENDING"}` stub. Stable `run_id`s make the resume deterministic.

This is the single most demo-worthy capability on the platform — build the demo around it.

---

## 7. Policy gate and bounded execution

Deterministic, in-process, roughly 150 lines, and the most heavily tested code in the repo.

```python
ACTION_POLICY = {
    "create_service_case":   {"risk": "LOW",    "approval": None},
    "assign_case":           {"risk": "LOW",    "approval": None},
    "attach_agent_summary":  {"risk": "LOW",    "approval": None},
    "notify_internal":       {"risk": "LOW",    "approval": None},
    "mark_duplicate":        {"risk": "LOW",    "approval": None},
    "remote_diagnostic":     {"risk": "MEDIUM", "approval": "fleet_ops_manager"},
    "customer_notification": {"risk": "MEDIUM", "approval": "account_manager"},
    "firmware_action":       {"risk": "HIGH",   "approval": "BLOCKED"},
}
```

Gate stages, in order, each emitting an audit record:

1. **Schema** — the recommendation validates against `recommendation.schema.json`, or the run fails closed.
2. **Allowlist** — every proposed action exists in `ACTION_POLICY`. An invented action is a hard failure, logged as a grounding violation.
3. **Risk tier** — `HIGH` is blocked outright and never surfaced as approvable.
4. **Approval matrix** — `MEDIUM` routes to the named reviewer role and triggers the pause.
5. **Escalation overlay** — fleet-specific rules (strategic tier escalates `CRITICAL_CONNECTIVITY`).
6. **Idempotency** — every execution carries `{incident_id}:{action_type}` so a resumed workflow cannot double-execute.

A recommendation can be *split*: `create_service_case` executes immediately while `remote_diagnostic` waits for approval. Demonstrating partial execution is worth more than an all-or-nothing gate.

---

## 8. Deployment

### 8.1 Bootstrap

```bash
export PROJECT_ID=fleetops-ai-lab
export LOCATION=us-central1
export BUCKET=gs://${PROJECT_ID}-agent-staging

gcloud services enable \
  aiplatform.googleapis.com storage.googleapis.com run.googleapis.com \
  cloudfunctions.googleapis.com firestore.googleapis.com \
  cloudscheduler.googleapis.com cloudbuild.googleapis.com \
  cloudtrace.googleapis.com --project=$PROJECT_ID

gcloud storage buckets create $BUCKET --location=$LOCATION
gcloud firestore databases create --location=$LOCATION --type=firestore-native

gcloud auth application-default login
pip install --upgrade "google-cloud-aiplatform[agent_engines,adk]>=1.112" "google-adk>=2.5"
```

IAM required on the deploying principal: `roles/aiplatform.user`, `roles/storage.admin`, `roles/run.admin`, `roles/datastore.user`.

### 8.2 Data plane and tools

```bash
gcloud run deploy fleetops-synth-fn  --source ./synth  --region=$LOCATION --no-allow-unauthenticated
gcloud run deploy fleetops-tools-mcp --source ./mcp    --region=$LOCATION --no-allow-unauthenticated
```

### 8.3 Agent

```text
fleetops_control_agent/
├── __init__.py          # from . import agent
├── agent.py             # defines root_agent
├── requirements.txt
├── .env                 # GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION /
│                        # GOOGLE_GENAI_USE_VERTEXAI=1 / MCP_URL
└── skills/              # the skill pack
```

```bash
adk deploy agent_engine \
  --project=$PROJECT_ID \
  --region=$LOCATION \
  --staging_bucket=$BUCKET \
  --display_name="FleetOps Control Agent" \
  --trace_to_cloud \
  fleetops_control_agent
```

Returns a `RESOURCE_ID`; the agent is then addressable at
`https://${LOCATION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${LOCATION}/reasoningEngines/${RESOURCE_ID}`.

Deploy with `identity_type=AGENT_IDENTITY` so the agent carries its own service identity when calling the MCP service, rather than borrowing the caller's credentials. Grant that identity `roles/run.invoker` on `fleetops-tools-mcp`.

Locally, `adk web` runs the same graph with in-memory sessions; deployed, Agent Runtime provisions managed sessions automatically. Do not write code that assumes in-memory session state.

### 8.4 Console

```bash
gcloud run deploy fleetops-console --source ./console --region=$LOCATION --allow-unauthenticated
```

Streams `async_stream_query`, renders the evidence panel, and posts the approve/reject that resumes the paused run.

---

## 9. Evals and observability

**Eval set — 12 scenarios** (`adk eval`), each a fixed event batch plus expected outcome:

| Class | Count | Examples |
|---|---|---|
| Functional | 4 | golden battery/connectivity; safety cluster; firmware rollback; benign noise producing *no incident* |
| Safety | 3 | firmware action must be blocked; customer notification must never auto-send; prompt-injection string inside an event payload must not alter the gate |
| Grounding | 2 | recommendation cites a playbook that was actually loaded; no invented vehicle facts |
| Business logic | 2 | strategic fleet outranks standard fleet on identical signals; score is exactly reproducible |
| Regression | 1 | the golden scenario pinned to score 87 / P1 |

The two hardest to fake and most worth having are **"benign noise produces no incident"** (an agent that always finds something is useless in a command center) and **prompt injection in a telemetry payload** (the deterministic gate is what makes that survivable — demonstrate it).

**Observability.** `--trace_to_cloud` gives Cloud Trace spans per node. Add a `correlation_id` on every audit record spanning event → incident → tool calls → recommendation → gate decision → approval → action, and surface it in the console so a demo viewer can follow one incident through the whole trace.

**Metrics to publish in the README:** incidents/hour, correlation precision, LLM calls per incident, p95 decision latency, gate block rate, approval turnaround, grounding-citation rate.

---

## 10. Build phases

| Phase | Deliverable | Done when | Est. |
|---|---|---|---|
| 0 | GCP bootstrap | `adk web` runs a hello agent locally; `adk deploy agent_engine` succeeds on a stub | 0.5d |
| 1 | Seeded generator + `fleetops-synth-fn` + Firestore | `/scenario/battery_connectivity` writes the golden cluster; `/tick` writes ambient noise | 1.5d |
| 2 | `fleetops-tools-mcp` | All 17 tools return valid synthetic JSON; unit tests green; MCP Inspector connects | 2d |
| 3 | Skill pack | `load_skill` returns each skill; 3 playbooks authored | 1d |
| 4 | Deterministic workflow spine | correlate → score → gate → execute → audit runs end to end **with no LLM** | 1d |
| 5 | Triage + Recommendation LLM nodes | Structured outputs validate; golden scenario produces the expected recommendation | 2d |
| 6 | Policy gate + HITL pause/resume | Run pauses at `RequestInput`, survives process restart, resumes correctly, split execution works | 2d |
| 7 | Deploy to Agent Runtime | `RESOURCE_ID` answers a `streamQuery`; traces land in Cloud Trace | 0.5d |
| 8 | Console | Approve and reject paths both work against the deployed agent | 1.5d |
| 9 | Evals + observability | 12/12 eval scenarios pass in CI; correlation ID traceable end to end | 1.5d |
| 10 | Demo script, README, teardown | 5-minute recorded walkthrough | 1d |

**Roughly 14 working days.** Phase 4 is the critical checkpoint: *the entire pipeline must work with zero LLM calls before any model is added.* If the deterministic spine is not green, adding a model only hides the bug.

---

## 11. Cost and teardown

Idle cost is near zero: Cloud Run and the function scale to zero, Firestore stays in free tier at this volume, Agent Runtime bills per use. The only recurring risk is a live Cloud Scheduler job, which is **paused by default** in this plan.

Ship `scripts/teardown.sh` — `remote_agent.delete(force=True)`, delete the three Cloud Run services, clear Firestore, delete the staging bucket — and mention it in the README. Reviewers notice.

---

## 12. Risks and open items to verify

| Item | Risk | Mitigation |
|---|---|---|
| Skill `scripts/` egress from the Agent Runtime sandbox | Unverified whether skill scripts can reach Cloud Run | Keep skills knowledge-only; all data via MCP tools. Verify in Phase 3 before depending on it. |
| MCP cold start vs ADK timeout | Intermittent handshake failures | Explicit 30s timeout; set Cloud Run `min-instances=1` during a live demo only. |
| ID token expiry on long HITL pauses | Resume fails auth after a multi-hour pause | Mint the token per tool call, not once at agent construction. |
| HITL resume semantics across a redeploy | Checkpoint may not survive a version change | Do not redeploy mid-demo; use stable `run_id`s; test restart-then-resume in Phase 6. |
| Model version drift | `gemini-3.5-flash` vs `3.6-flash` output differences | Pin the model ID in config; gate any change on the eval set. |
| Structured output adherence | Model returns prose instead of schema | `output_schema` + independent re-validation at the gate + fail closed. |
| `gemini-2.5-*` shutdown 2026-10-20 | Hard breakage if used | Do not use the 2.5 family. |

---

## 13. Changes applied to `AGENTIC.md`

1. **Added an LLM-requirement table** — the doc named five agents without saying which need a model. Two do.
2. **Separated Skill / Tool / Service** — "skill" was used for both knowledge packages and callable functions; ADK 2.5 gives these distinct meanings.
3. **Playbooks as Skills** replaces the vector-database assumption at MVP scale, with the Skill Registry named as the scale path.
4. **Consolidated six MCP servers to one** for the MVP, keeping the six groupings as tool namespaces.
5. **Real HITL** — the "Human Approval Skill" returning `PENDING` became a genuine `RequestInput` pause with checkpointed resume.
6. **Concrete MVP flow** — the ten numbered steps now name the component, the LLM/no-LLM decision, and the artifact each step produces.
7. **Refreshed the GCP table** to current product naming and added agent identity and tracing rows.
8. **Aligned ID conventions** with the repository's `veh_` / `flt_` prefixes.
9. **Streaming deferred** — Pub/Sub is a Phase-2 upgrade, not an MVP dependency.
