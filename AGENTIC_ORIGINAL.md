## Prototype idea: FleetOps AI Control Lab

Build a **synthetic telematics multi-agent system** where a collection of agents monitors fleet telemetry signals, detects operational exceptions, retrieves synthetic context through skills/tools, prioritizes incidents, recommends actions, and routes high-risk actions for human review.

The goal is to demonstrate:

> Production-grade agentic AI for operational command centers using synthetic telematics data, skills, tool calls, guardrails, evals, observability, and GCP Agent Platform deployment.

Google’s current Agent Platform supports building agents with the Agent Development Kit and deploying them to Agent Runtime; the docs describe ADK as a modular, model-agnostic framework for complex agents, with Runtime / Cloud Run / GKE deployment options. ([Google Cloud Documentation][1]) Google also documents deployment of ADK agents on Agent Platform Runtime through a `reasoningEngine` resource, and notes that locally ADK apps can use in-memory sessions while deployed agents use cloud-managed sessions. ([Google Cloud Documentation][2])

# 1. Prototype narrative

Use a fictional company:

> **NovaFleet Mobility** operates commercial fleets across regions. Vehicles continuously emit synthetic telemetry: health, location, connectivity, safety, remote-command, and firmware signals. FleetOps AI Control Lab monitors those signals, detects exceptions, prioritizes risk, retrieves relevant synthetic context, recommends next actions, and routes actions through policy and human approval.

The system should demonstrate this flow:

```text
Synthetic Telematics Streams
        ↓
Signal Monitor Agents
        ↓
Fleet Digital Twin / State Store
        ↓
Contextual Prioritization
        ↓
Specialized Skills / MCP Tools
        ↓
Recommendation + Policy Gate
        ↓
HITL Approval or Bounded Action
        ↓
Audit / Evals / Observability
```

The key design principle:

> Agents do not directly “know” fleet facts. They rely on skills. Skills call synthetic MCP/UCP tools. Tools return synthetic but realistic responses.

# 2. Agent collection

Keep the agent system disciplined. Do not create ten agents just to show multi-agent complexity.

## A. Fleet Signal Monitor Agent

**Purpose:** Watches synthetic telemetry streams and identifies abnormal patterns.

Inputs:

* vehicle health events
* location events
* connectivity events
* safety events
* remote command events
* firmware/OTA events

Responsibilities:

* detect unusual telemetry patterns
* classify whether the event is normal, warning, urgent, or critical
* group related events into an incident candidate
* call skills for vehicle/fleet context
* send incident candidates to the triage layer

Example output:

```json
{
  "incident_candidate_id": "IC-10482",
  "vehicle_id": "VH-10482",
  "event_cluster": ["LOW_BATTERY_VOLTAGE", "MISSED_HEARTBEAT", "REMOTE_DIAGNOSTIC_FAILED"],
  "initial_severity": "HIGH",
  "reason": "Multiple related signals indicate possible vehicle power or connectivity degradation."
}
```

## B. Vehicle Health Triage Agent

**Purpose:** Determines likely cause and operational seriousness.

Responsibilities:

* retrieve recent vehicle history
* check diagnostic codes
* compare current event pattern to prior synthetic incidents
* identify likely issue category
* recommend whether the incident needs prioritization

Skills used:

* Vehicle Profile Skill
* Vehicle Event History Skill
* Similar Incident Search Skill
* Diagnostic Interpretation Skill

## C. Fleet Impact Prioritization Agent

**Purpose:** Ranks incidents based on business context, not just technical severity.

Responsibilities:

* calculate fleet/customer impact
* check SLA exposure
* detect whether the fleet is high-priority
* evaluate geographic concentration
* prioritize the incident queue

Skills used:

* Fleet Contract Skill
* SLA Risk Skill
* Geo-Cluster Skill
* Composite Priority Skill

This is the most important “enterprise AI” part of the prototype.

## D. Recommendation Agent

**Purpose:** Generates next-best action with evidence.

Responsibilities:

* retrieve relevant playbook/policy
* generate a structured recommendation
* include rationale and alternatives
* identify required approval level
* produce JSON output for validation

Skills used:

* Playbook Retrieval Skill
* Prior Resolution Skill
* Action Recommendation Skill
* Communication Draft Skill

## E. Policy Gate Agent / Policy Gate Service

This should mostly be deterministic, even if you call it an agent.

**Purpose:** Enforces whether the recommendation can be shown, routed, or executed.

Responsibilities:

* validate output schema
* verify action eligibility
* check risk tier
* require approval for restricted actions
* block unsafe actions
* record audit event

This is where you demonstrate architecture maturity.

# 3. Skills to build

Each agent should use **skills** rather than hardcoding all logic inside the agent prompt.

## 1. Vehicle Profile Skill

Returns synthetic vehicle facts.

Example request:

```json
{
  "vehicle_id": "VH-10482"
}
```

Example synthetic response:

```json
{
  "vehicle_id": "VH-10482",
  "make": "Aster",
  "model": "MetroVan 250",
  "year": 2022,
  "fleet_id": "FL-204",
  "region": "Southeast",
  "telematics_unit_id": "TU-88721",
  "service_tier": "Premium",
  "odometer_miles": 84210,
  "current_state": "IN_SERVICE"
}
```

## 2. Recent Telemetry Skill

Returns recent synthetic telemetry for a vehicle.

Example response:

```json
{
  "vehicle_id": "VH-10482",
  "window": "last_60_minutes",
  "events": [
    {
      "timestamp": "2026-09-05T18:40:00Z",
      "event_type": "LOW_BATTERY_VOLTAGE",
      "value": 11.4,
      "severity": "WARNING"
    },
    {
      "timestamp": "2026-09-05T18:45:00Z",
      "event_type": "MISSED_HEARTBEAT",
      "severity": "WARNING"
    },
    {
      "timestamp": "2026-09-05T18:47:00Z",
      "event_type": "REMOTE_DIAGNOSTIC_FAILED",
      "severity": "HIGH"
    }
  ]
}
```

## 3. Diagnostic Interpretation Skill

Maps synthetic DTCs and telemetry patterns to likely issue categories.

Example output:

```json
{
  "likely_issue": "POWER_SYSTEM_DEGRADATION",
  "confidence": 0.78,
  "supporting_signals": [
    "low voltage",
    "missed heartbeat",
    "remote diagnostic failure"
  ],
  "needs_human_review": true
}
```

## 4. Fleet Contract / SLA Skill

Retrieves synthetic fleet contract context.

Example output:

```json
{
  "fleet_id": "FL-204",
  "customer_tier": "Strategic",
  "sla": {
    "critical_response_hours": 2,
    "high_response_hours": 8
  },
  "escalation_required_for": ["SAFETY", "CRITICAL_CONNECTIVITY", "PREMIUM_FLEET_DOWN"]
}
```

## 5. Prior Incident Search Skill

Returns similar synthetic incidents.

Example output:

```json
{
  "similar_incidents": [
    {
      "incident_id": "INC-7712",
      "pattern": "LOW_BATTERY + MISSED_HEARTBEAT + REMOTE_DIAG_FAIL",
      "root_cause": "loose battery terminal",
      "resolution": "schedule mobile service inspection",
      "time_to_resolve_hours": 6
    }
  ]
}
```

## 6. Playbook Retrieval Skill

Retrieves synthetic policies/SOPs.

Example output:

```json
{
  "playbook_id": "PB-BATTERY-002",
  "title": "Battery Degradation and Connectivity Loss Playbook",
  "required_steps": [
    "confirm recent voltage trend",
    "check connectivity heartbeat",
    "attempt remote diagnostic only if approved",
    "create service case for strategic fleet if voltage remains below threshold"
  ],
  "approval_required_for": ["REMOTE_DIAGNOSTIC", "CUSTOMER_NOTIFICATION"]
}
```

## 7. Priority Scoring Skill

Calculates deterministic score, then allows the agent to explain it.

Example output:

```json
{
  "priority_score": 87,
  "priority": "P1",
  "components": {
    "safety_risk": 20,
    "sla_exposure": 25,
    "fleet_priority": 20,
    "recurrence": 12,
    "confidence": 10
  },
  "explanation": "High priority due to strategic fleet SLA, recurring power/connectivity signals, and failed remote diagnostic."
}
```

## 8. Recommendation Skill

Produces next-best action.

Example output:

```json
{
  "recommended_action": "CREATE_SERVICE_CASE_AND_REQUEST_REMOTE_DIAGNOSTIC_APPROVAL",
  "risk_tier": "MEDIUM",
  "requires_human_approval": true,
  "rationale": "The vehicle belongs to a strategic fleet and has recurring power/connectivity indicators.",
  "alternatives": [
    "Monitor for 30 minutes",
    "Create service case only",
    "Escalate to fleet operations"
  ]
}
```

## 9. Human Approval Skill

Simulates HITL.

Example outcomes:

```json
{
  "approval_id": "APP-10091",
  "status": "PENDING",
  "reviewer_role": "Fleet Operations Manager",
  "action": "REMOTE_DIAGNOSTIC"
}
```

## 10. Bounded Execution Skill

Executes only mock actions.

Allowed actions:

* create service case
* route case
* attach summary
* request approval
* mark duplicate
* send internal notification

Restricted actions:

* customer-facing message
* remote diagnostic
* firmware action

# 4. MCP / UCP endpoint design

Use MCP-style tool servers to make the project look like a real agentic architecture. Use UCP as your logical **Unified Context Provider** if you want a clean abstraction over synthetic context.

## MCP server 1: `fleet-master-mcp`

Tools:

* `get_vehicle_profile(vehicle_id)`
* `get_fleet_profile(fleet_id)`
* `get_fleet_sla(fleet_id)`
* `list_vehicles_by_fleet(fleet_id)`

## MCP server 2: `telematics-events-mcp`

Tools:

* `get_recent_vehicle_events(vehicle_id, window_minutes)`
* `search_events_by_type(event_type, window_minutes)`
* `search_events_by_region(region, window_minutes)`
* `get_active_alerts(vehicle_id)`

## MCP server 3: `fleet-context-ucp`

Tools:

* `get_vehicle_operational_state(vehicle_id)`
* `get_fleet_operational_state(fleet_id)`
* `get_dependency_graph(entity_id)`
* `get_downstream_impact(event_id)`

## MCP server 4: `playbook-rag-mcp`

Tools:

* `search_playbooks(query)`
* `get_playbook(playbook_id)`
* `search_similar_incidents(event_signature)`
* `get_incident_resolution(incident_id)`

## MCP server 5: `risk-policy-mcp`

Tools:

* `calculate_priority_score(event_id)`
* `get_action_eligibility(action_type, risk_tier)`
* `get_required_approval(action_type)`
* `validate_recommendation(recommendation_json)`

## MCP server 6: `workflow-actions-mcp`

Tools:

* `create_service_case(vehicle_id, recommendation)`
* `assign_case(case_id, team)`
* `attach_agent_summary(case_id, summary)`
* `request_human_approval(action)`
* `record_approval_decision(approval_id, decision)`

For the prototype, each tool can return synthetic JSON responses from SQLite/Postgres tables or generated fixtures.

# 5. Synthetic data and streaming tasks

## A. Synthetic master data generator

Generate:

* vehicles
* telematics units
* fleets
* service tiers
* regions
* drivers/operators
* service providers
* playbooks
* incident history
* SLA rules
* risk policies

MVP size:

* 500 vehicles
* 20 fleets
* 8 regions
* 10 event types
* 5 playbooks
* 100 prior incidents

## B. Artificial telemetry streamer

Generate events every few seconds.

Streams:

* vehicle health stream
* vehicle state stream
* connectivity stream
* geolocation stream
* safety event stream
* remote command stream
* firmware/OTA stream

Synthetic event patterns:

* normal driving
* gradual battery degradation
* connectivity outage in a region
* repeated remote diagnostic failures
* harsh braking cluster
* GPS drift
* firmware rollback failure
* missed heartbeat
* SLA-sensitive strategic fleet alert
* duplicate/out-of-order events

This is important because it shows you understand production data is messy.

# 6. GCP deployment model

A practical GCP prototype could use:

| Layer               | GCP option                                             |
| ------------------- | ------------------------------------------------------ |
| Agent runtime       | Google Agent Platform Runtime / Vertex AI Agent Engine |
| Agent framework     | ADK                                                    |
| Synthetic streaming | Pub/Sub                                                |
| Event processing    | Cloud Run functions/services                           |
| State store         | Firestore, AlloyDB, or Cloud SQL                       |
| Analytics           | BigQuery                                               |
| Vector/RAG          | Vertex AI Vector Search                                |
| Object/doc storage  | Cloud Storage                                          |
| Observability       | Cloud Logging, Cloud Trace, OpenTelemetry              |
| UI                  | Cloud Run-hosted Streamlit/React                       |
| CI/CD               | Cloud Build                                            |

For the portfolio version, keep it local-first with Docker Compose, then add a GCP deployment path.

Google documentation indicates ADK agents can be developed and deployed on Agent Runtime, and ADK agents can also be deployed to Cloud Run. ([Google Cloud Documentation][2])

# 7. Prototype scope

Do not try to build full fleet management. Build one polished flow.

## MVP demo flow

1. Synthetic streamer emits 200 vehicle events.
2. Fleet Signal Monitor Agent detects a cluster:

   * low battery voltage
   * missed heartbeat
   * remote diagnostic failure
3. Triage Agent classifies issue as power/connectivity degradation.
4. Context Skill retrieves:

   * vehicle profile
   * fleet SLA
   * prior similar incidents
   * battery/connectivity playbook
5. Prioritization Agent assigns P1/P2/P3.
6. Recommendation Agent proposes next action.
7. Policy Gate determines:

   * create service case = allowed
   * remote diagnostic = requires approval
   * customer notification = requires approval
8. HITL UI shows recommendation and evidence.
9. User approves or rejects.
10. Audit log captures:

* event
* context
* tools called
* recommendation
* policy decision
* approval outcome

# 8. Portfolio packaging

Your GitHub README should say:

> FleetOps AI Control Lab is a synthetic telematics command-center simulation. It demonstrates how agents can monitor fleet signals, retrieve context through skills, prioritize exceptions, recommend actions, route high-risk actions for human approval, and log decisions for observability and audit. The project uses synthetic data only and does not use employer data, code, architecture, or proprietary business rules.

Resume bullet:

> Built FleetOps AI Control Lab, a synthetic telematics multi-agent system on GCP Agent Platform concepts, demonstrating ADK-based agents, skill-driven tool use, synthetic MCP/UCP services, RAG over playbooks and incidents, contextual prioritization, HITL approval, output validation, observability, and bounded execution.

Interview framing:

> I wanted a public execution artifact that showed production AI architecture without using employer data. I chose telematics because it is a signal-heavy operational domain: vehicles produce telemetry, command centers surface exceptions, and operators need context, prioritization, recommendations, and controlled action. The implementation uses synthetic data and mock skills/tools to demonstrate the architecture pattern safely.

[1]: https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/adk "Agent Development Kit  |  Gemini Enterprise Agent Platform  |  Google Cloud Documentation"
[2]: https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/quickstart-adk "Quickstart: Develop and deploy agents on Agent Runtime with Agent Development Kit  |  Gemini Enterprise Agent Platform  |  Google Cloud Documentation"
