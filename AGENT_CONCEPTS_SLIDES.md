---
marp: true
theme: default
paginate: true
size: 16:9
header: 'Building Governed AI Agents'
footer: 'FleetOps AI Control Lab'
---

<!-- _class: lead -->
# Building Governed AI Agents
### From concepts to a production architecture
#### FleetOps AI Control Lab — Teaching Deck

---

## Agenda

1. Overview of Agents
2. Techniques of Building Agents
3. Overview of the Agent Platform
4. Overview of ADK
5. Deployment Architecture of Our Solution
6. Non-Functional Requirements

---

<!-- _class: lead -->
# 1. Overview of Agents

---

## What is an AI Agent?

- A system that **perceives, reasons, and acts** to reach a goal — not just answers a question
- Loop: **observe → think → act → observe…** until done
- Difference from a plain LLM call:
  - LLM call — one prompt in, one completion out
  - Agent — the LLM **decides what to do next**, calls tools, observes results, continues

> An agent = an LLM given tools, memory, and a loop.

---

## Anatomy of an Agent

| Component | Role |
|---|---|
| **Model (reasoning)** | Interprets context, decides the next action |
| **Tools** | Typed functions the agent can call to observe/affect the world |
| **Memory** | Session state, conversation history, retrieved knowledge |
| **Instructions** | System prompt, persona, constraints |
| **Orchestration** | Controls the loop — sequential, graph, multi-agent |
| **Guardrails** | Validation, policy, human approval |

---

## Why Agents, Why Now

- Models got good at **structured output** and **function/tool calling**
- Enterprises need **actions**, not just text — create a case, send a notification, approve a change
- The real design problem: **when should the model decide, and when should code decide?**
- This question drives everything else in this talk

---

<!-- _class: lead -->
# 2. Techniques of Building Agents

---

## Core Prompting Patterns

- **Chain-of-Thought** — reason step by step before answering
- **ReAct** (Reason + Act) — interleave reasoning with tool calls
- **Plan-and-Execute** — produce a plan, then execute each step under code control
- **Structured output** — force the model to answer against a schema (JSON/Pydantic) so downstream code can trust the shape

---

## Tool Use / Function Calling

- The model doesn't "do" anything — it emits a **structured intent**: `get_fleet_sla(fleet_id="flt_204")`
- The **runtime** executes the real call and returns the result
- This boundary is what makes agents safe: the model *proposes*, code *disposes*
- Tools should be **typed, narrow, and side-effect bounded** — never a generic "run any code" tool

---

## Retrieval: RAG vs. Skills

| | RAG (Vector DB) | Skills (progressive disclosure) |
|---|---|---|
| Best for | Large, unstructured corpora | Curated procedural knowledge (playbooks, SOPs) |
| Grounding | Similarity search — harder to cite | Agent names the skill it loaded — free citation |
| Ops cost | Embeddings pipeline, vector store | Just files (`SKILL.md`) shipped with the agent |
| Scale path | — | Migrate to a Skill Registry at 100s of items |

**Rule of thumb:** don't reach for a vector database before you've outgrown a well-organized skill pack.

---

## The Most Important Design Decision: Where Does the LLM Belong?

- LLMs are good at **ambiguity** — messy, partial, conflicting signals → a hypothesis
- LLMs are bad at **being a control** — non-reproducible, costly, slower, prompt-injectable
- Put an LLM only where **rules genuinely cannot resolve the task**
- Everything else — correlation, scoring, policy, execution, audit — stays **deterministic code**

---

## Worked Example: 10 Pipeline Steps, Only 2 Need an LLM

| Step | LLM? | Why |
|---|---|---|
| Event correlation | ❌ No | Sliding-window logic — a rules job |
| **Health triage** | ✅ Yes | Genuine ambiguity: form a cause hypothesis |
| Context retrieval | ❌ No | Parallel typed tool calls |
| Priority scoring | ❌ No | Weighted arithmetic — must be auditable |
| **Recommendation** | ✅ Yes | Real synthesis of playbook + evidence |
| Policy gate | ❌ **Never** | It's a security control |
| Execution / audit | ❌ No | Allowlist dispatch, append-only writes |

*A score or a security gate that a model can drift on is not a control.*

---

## Human-in-the-Loop (HITL)

- Some actions are too risky to fully automate — pause and ask a human
- Weak version: `{"status": "PENDING"}` — a stub with no real state
- Strong version: the **workflow itself halts**, state is checkpointed, and it can resume **hours later**, on a different process, from the exact step
- HITL is a **runtime capability** the platform must support — not just a UI feature

---

## Guardrails & Policy Gates

- Never let the model be the security boundary — its own inputs (including other model output) can be adversarial (**prompt injection**)
- A gate should be:
  1. **Schema-validated** — fail closed on malformed output
  2. **Allowlisted** — invented actions are hard failures
  3. **Risk-tiered** — LOW / MEDIUM / HIGH treated differently
  4. **Idempotent** — safe to resume without double-executing

---

## Multi-Agent Orchestration Patterns

- **Sequential** — fixed pipeline, A → B → C
- **Graph / Workflow** — nodes with branching, conditional edges, pause/resume
- **Fan-out / parallel** — independent tool calls executed concurrently
- **Supervisor + sub-agents** — one agent delegates to specialists

Choose the simplest pattern that supports the control you actually need — a real pause requires a graph workflow, not a plain sequential agent.

---

## Evals: Testing Agents Like Software

- Fixed input → expected outcome, run in CI — not vibes-based
- Categories to cover:
  - **Functional** — golden path works
  - **Safety** — dangerous actions are blocked, injection doesn't change the gate
  - **Grounding** — no hallucinated facts, citations are real
  - **Regression** — a pinned scenario stays pinned (same score, same class)

---

<!-- _class: lead -->
# 3. Overview of the Agent Platform

---

## What "Agent Platform" Means

- A **managed runtime** for deployed agents — not just a model API
- Google's stack: **Gemini Enterprise Agent Platform**
  - **Agent Runtime** (`reasoningEngine`) — the managed execution environment
  - **ADK** — the framework you write the agent in (next section)
- The platform's job: sessions, scaling, tracing, identity — so you don't hand-roll infrastructure for every agent

---

## Agent Runtime Capabilities

| Capability | What it gives you |
|---|---|
| **Managed sessions** | Conversation/workflow state persisted automatically — no in-memory assumptions |
| **HITL pause/resume** | `RequestInput` halts a run; it can resume hours later, on any process |
| **Tracing** | One deploy flag (`--trace_to_cloud`) → spans per node in Cloud Trace |
| **Identity** | Agent can carry its **own** service identity (`AGENT_IDENTITY`), not the caller's |
| **Scale** | Pay per use; no idle servers to manage |

---

## Local Dev vs. Deployed

| | `adk web` (local) | Agent Runtime (deployed) |
|---|---|---|
| Sessions | In-memory | Managed, durable |
| Identity | Developer credentials | Agent's own service identity |
| Tracing | Console only | Cloud Trace / Cloud Logging |
| Addressing | `localhost` | `.../reasoningEngines/{RESOURCE_ID}` |

**Rule:** never write code that assumes in-memory session state — it breaks the moment it's deployed.

---

<!-- _class: lead -->
# 4. Overview of ADK

---

## What is ADK?

- **Agent Development Kit** — Google's Python framework for building agents that run on the Agent Platform
- Gives you the primitives from Section 2 as first-class objects:
  - `LlmAgent` — a model-backed reasoning node
  - `Workflow` / `@node` — deterministic + LLM steps composed into a graph
  - `Skills` — packaged procedural knowledge
  - `McpToolset` — typed tools over MCP (Model Context Protocol)

---

## Three Layers ADK Keeps Distinct

| Layer | ADK concept | Contains | Example |
|---|---|---|---|
| **Skill** | `SKILL.md` in a `SkillToolset` | *How to reason* — instructions, references | "How to interpret a power/connectivity signal cluster" |
| **Tool** | `McpToolset` (streamable HTTP) | *What is true* — a typed, bounded call | `get_fleet_sla(fleet_id)` |
| **Service** | Cloud Run | The real implementation behind the tool | `fleetops-tools-mcp` |

**Rule:** agents hold no domain facts. Skills say how to reason; tools return what is true.

---

## `LlmAgent`: the Model-Backed Node

```python
triage_agent = LlmAgent(
    name="triage",
    model="gemini-3.5-flash",
    instruction=TRIAGE_INSTRUCTION,   # loads a Skill
    tools=[fleet_skills, fleet_tools],
    output_schema=TriageHypothesis,   # structured output
    output_key="triage",
)
```

- `output_schema` forces structured output — the contract downstream code relies on
- Tools are attached explicitly and scoped per agent

---

## `Workflow` / `@node`: the Graph

```python
@node()                          # deterministic, no LLM
async def score_priority(ctx, node_input): ...

@node(rerun_on_resume=False)
async def human_approval(ctx, node_input):
    yield RequestInput(message=render_approval_card(node_input))
```

- Mix deterministic `@node` functions with `LlmAgent` nodes in one graph
- `ctx.run_node(..., run_id=stable_id)` makes resume deterministic
- `RequestInput` is a **real pause** — not a polling stub

---

## Why a Graph `Workflow`, not `SequentialAgent`

- `SequentialAgent` runs straight through — no true pause
- `Workflow` + `RequestInput` **halts the run**, persists the checkpoint, and can resume on a different process, hours later, skipping already-completed sub-nodes
- Usually **the single most demo-worthy capability** the platform offers — HITL that actually holds

---

## MCP Tools in ADK

```python
fleet_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=MCP_URL,
        headers={"Authorization": f"Bearer {id_token}"},
        timeout=30,   # default ~5s is shorter than a Cloud Run cold start
    )
)
```

- MCP = **Model Context Protocol** — a standard way to expose typed tools over HTTP
- One MCP service can expose many **namespaced tool groups** (`master.*`, `events.*`, `risk.*`, `actions.*`)
- Consolidate: 6 logical tool groups → 1 deployable, not 6

---

## Skills in ADK

```python
# Candidate imports: verify against the Phase 0 lockfile
from google.adk.skills import load_skill_from_dir
from google.adk.tools import skill_toolset
fleet_skills = skill_toolset.SkillToolset(skills=[...])
```

- Each Skill = a folder with `SKILL.md` (+ references, schemas, scripts)
- Discovery is **description-based** — the agent matches its need against each skill's `description`
- Loading is **on-demand** (progressive disclosure) and **citable** — the agent names the skill it used
- Scale path: migrate the pack to the **Skill Registry** when it grows to hundreds of items

---

<!-- _class: lead -->
# 5. Deployment Architecture of Our Solution

---

## The Four Deployables

```
Manual inject + analyze (from the console)
        │
        ▼
fleetops-synth-fn ........ Cloud Run service (FastAPI) — synthetic data + scenario injection
        │
        ▼
fleetops-tools-mcp ....... Cloud Run service — MCP tool surface (deterministic, tested)
        │
        ▼
fleetops-control-agent ... Agent Runtime — the ADK graph Workflow
        │
        ▼
fleetops-console ......... Cloud Run (Streamlit) — HITL approve/reject UI
        │
        ▼
Cloud Trace + Cloud Logging
```

---

## Layer-by-Layer Choices

| Layer | Product | Why |
|---|---|---|
| Agent runtime | Agent Runtime (`reasoningEngine`) | Managed sessions + HITL resume + tracing |
| Framework | ADK 2.5 (Python) | Graph Workflows, Skills, MCP client |
| Synthetic data | Cloud Run function | Stateless, scales to zero, reseedable |
| Event log | Firestore (Native) | Free tier, no migrations, append-only fit |
| Tools | Cloud Run + MCP | Real agent-safe boundary |
| Knowledge | ADK Skills | No vector DB needed at this scale |
| UI | Streamlit on Cloud Run | Fastest credible HITL screen |
| Observability | Cloud Trace/Logging via OTel | One deploy flag |

---

## The Agent's Own Graph

```
ingest → correlate → TRIAGE (LLM) → context fan-out
   → score → explain (LLM) → RECOMMEND (LLM)
   → policy gate → [HITL pause] → execute → audit
```

- Only **3 of ~9 steps** touch a model
- The pause sits **after** recommendation and **before** irreversible action — exactly where governance belongs

---

## Policy Gate — the Deterministic Core

```python
ACTION_POLICY = {
    "create_service_case":   {"risk": "LOW",    "approval": None},
    "remote_diagnostic":     {"risk": "MEDIUM", "approval": "fleet_ops_manager"},
    "customer_notification": {"risk": "MEDIUM", "approval": "BLOCKED"},
    "firmware_action":       {"risk": "HIGH",   "approval": "BLOCKED"},
}
```

Six ordered stages, each audited: **schema → allowlist → risk tier → approval matrix → escalation overlay → idempotency**

A recommendation can be **split** — low-risk parts execute immediately, higher-risk parts wait for approval.

---

## End-to-End Walkthrough (Golden Scenario)

1. Three signals land within 12 minutes on `veh_10482` (strategic-tier fleet)
2. Deterministic correlation groups them into one incident
3. **LLM** forms a cause hypothesis (Triage)
4. Deterministic tools fetch SLA, playbook, prior incidents
5. Deterministic scoring → `P1`, score 87
6. **LLM** drafts a recommendation: create case + request remote diagnostic
7. Gate allows the case creation, **pauses** for the diagnostic approval
8. Human approves → resumes → executes → audit trail written

---

<!-- _class: lead -->
# 6. Non-Functional Requirements

---

## Reliability & Idempotency

- Every execution carries `{incident_id}:{action_type}` — a resumed workflow **cannot double-execute**
- Stable `run_id`s make resume deterministic across process restarts
- HITL checkpoints must survive a process dying mid-pause

---

## Security

- Policy gate is **never** an LLM — it must not be prompt-injectable by its own (model-generated) inputs
- Fail **closed** on schema violation or an unrecognized action
- Agent carries its **own** service identity (`AGENT_IDENTITY`) rather than borrowing the caller's
- Customer communication is out of MVP scope: drafting is deferred and `customer_notification` is **blocked**

---

## Observability

- `--trace_to_cloud` → per-node spans in Cloud Trace, one flag
- A single **correlation ID** threads: event → incident → tool calls → recommendation → gate decision → approval → action
- Publish operational metrics: incidents/hour, LLM calls/incident, p95 decision latency, gate block rate, approval turnaround, grounding-citation rate

---

## Reproducibility & Testability

- Master data is a **pure function** of entity ID (seeded PRNG) — same ID, same facts, every environment
- Deterministic components (correlation, scoring, gate) are unit-testable and drift-free
- 12-scenario eval suite in CI: functional, safety, grounding, business logic, regression — must pass before any model change ships

---

## Cost & Lifecycle

- Every compute layer **scales to zero** (Cloud Run, the function); Agent Runtime bills per use
- Cloud Scheduler is **not provisioned** in the MVP — nothing should bill quietly
- `teardown.ps1` removes only the resources recorded for the demo deployment, with a dry run first

---

## Latency & Model Risk

- Only 4 LLM calls per incident → roughly **2–4 seconds** of model latency total
- Model version is **pinned**; any change is gated on the eval set before it ships
- Deprecated model families are tracked and retired ahead of shutdown dates

---

<!-- _class: lead -->
# Key Takeaways

---

## Key Takeaways

1. An agent is a model + tools + memory + a loop — not magic, not a chatbot
2. The best design question: **"does this step need judgment, or a rule?"**
3. Skills carry *how to reason*; tools carry *what is true*; services hold the facts
4. HITL is only real if the **runtime** can pause, checkpoint, and resume — not a status flag
5. The policy gate is a **security control** — deterministic, tested, never model-driven
6. Non-functional requirements (idempotency, tracing, cost, reproducibility) are part of the architecture, not an afterthought

---

<!-- _class: lead -->
# Questions?

Reference: `MVP-DEMO-UPDATED.md` — FleetOps AI Control Lab
