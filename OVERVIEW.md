# FleetOps AI Control Lab: Strategy Overview

## 1. Purpose

**FleetOps AI Control Lab** is a synthetic telematics command-center simulation designed to demonstrate production-grade agentic AI patterns.

The goal is not to build a toy chatbot over vehicle data. The goal is to show how an enterprise AI system can ingest operational signals, maintain contextual state, prioritize exceptions, use tools, retrieve knowledge, recommend actions, enforce guardrails, and support human-in-the-loop decision-making.

The project should demonstrate:

* agentic AI architecture
* synthetic data generation
* streaming event processing
* operational digital twin modeling
* contextual prioritization
* RAG over playbooks and incident history
* MCP/UCP-style tool integration
* human approval workflows
* output validation
* evaluation harnesses
* observability and auditability
* bounded autonomous execution

The entire project should use synthetic data only. It should not use data, code, architecture, APIs, or business rules from any current or former employer.

---

## 2. Positioning

The project should be positioned as:

> A synthetic telematics command-center lab that demonstrates how agentic AI can move enterprise operations from signal visibility to contextual prioritization, recommendation, human approval, and controlled action.

This supports a broader professional positioning:

> Enterprise AI architecture for complex operational systems.

Telematics is a strong domain because it naturally involves:

* high-volume event streams
* vehicle health telemetry
* geospatial signals
* connectivity events
* diagnostic trouble codes
* incident triage
* safety escalation
* fleet SLA management
* customer/fleet communication
* operational decision support

---

## 3. Target Scenario

A fictional fleet-management company, **NovaFleet Mobility**, operates thousands of connected vehicles across multiple regions.

Vehicles continuously emit synthetic telemetry such as:

* engine health
* battery voltage
* diagnostic trouble codes
* odometer readings
* ignition state
* fuel or charge level
* connectivity status
* location coordinates
* harsh braking or acceleration
* remote command success/failure
* firmware update state
* safety alerts

The AI control lab ingests these events, updates a fleet digital twin, identifies operational exceptions, prioritizes impact, retrieves relevant context, recommends next actions, and routes high-risk actions for human approval.

---

# 4. Skills to Build

The project should be organized around reusable AI skills. A skill is a domain capability that may combine prompts, tools, policies, retrieval, validation, and workflow logic.

## 4.1 Vehicle Event Triage Skill

Purpose:

Classify incoming telematics events and determine whether they represent normal telemetry, warning conditions, urgent exceptions, or critical safety issues.

Inputs:

* vehicle event
* vehicle profile
* recent event history
* fleet contract
* active alerts
* prior incidents

Outputs:

* event category
* severity
* confidence
* recommended next step
* whether escalation is needed

Example classifications:

* normal telemetry
* degraded connectivity
* battery degradation
* critical diagnostic fault
* safety incident
* remote command failure
* firmware update failure
* SLA risk

---

## 4.2 Fleet Context Retrieval Skill

Purpose:

Retrieve relevant operational context before the agent makes a recommendation.

Sources:

* vehicle master data
* fleet master data
* service contracts
* synthetic incident history
* maintenance history
* playbooks
* support procedures
* policy documents
* recent telemetry trends

Outputs:

* relevant context bundle
* source references
* confidence in retrieved context
* missing-context warnings

---

## 4.3 Contextual Prioritization Skill

Purpose:

Rank vehicle exceptions based on business and operational impact.

Prioritization factors:

* safety risk
* vehicle criticality
* fleet customer priority
* SLA exposure
* number of affected vehicles
* recurrence
* geographic concentration
* confidence in signal
* downstream operational impact
* available remediation path

Outputs:

* priority score
* urgency level
* rationale
* top contributing factors
* recommended owner/team

---

## 4.4 Recommendation Skill

Purpose:

Generate recommended actions with supporting evidence.

Possible recommendations:

* monitor only
* request additional diagnostics
* notify fleet manager
* create service case
* schedule maintenance
* escalate to operations
* investigate connectivity issue
* retry remote diagnostic
* hold action pending human review

Outputs:

* recommended action
* alternative actions
* tradeoffs
* risks
* required approval level
* supporting evidence

---

## 4.5 Human Approval Skill

Purpose:

Route medium-risk or high-risk recommendations to a human reviewer.

Capabilities:

* create approval request
* display evidence
* show confidence score
* show risk classification
* capture approval/rejection
* capture reviewer comments
* update audit trail

Approval outcomes:

* approved
* rejected
* needs more information
* escalated
* deferred

---

## 4.6 Bounded Execution Skill

Purpose:

Execute low-risk, pre-approved actions.

Allowed low-risk actions:

* create ticket
* route case to queue
* request additional data
* attach summary to case
* notify internal team
* retry eligible data pull
* mark event as duplicate
* update synthetic incident state

Restricted actions requiring approval:

* customer-facing notification
* remote diagnostic command
* service appointment creation
* firmware action
* high-impact operational change

Blocked actions:

* disabling a vehicle feature
* changing vehicle safety behavior
* modifying contractual terms
* executing irreversible actions

---

## 4.7 Incident Learning Skill

Purpose:

Capture outcomes and use them to improve future prioritization and recommendation quality.

Inputs:

* original event
* recommendation
* human decision
* final action
* resolution status
* time to resolve
* reviewer feedback

Outputs:

* updated incident history
* evaluation data
* recurring pattern detection
* recommendation quality metrics

---

# 5. MCP / UCP Server Endpoints to Build

The project should expose mock tools through MCP-style or UCP-style interfaces.

For this project:

* **MCP** can represent agent-accessible tools and resources.
* **UCP** can represent a unified context layer that exposes enterprise state, policies, and operational context consistently to agents.

If UCP is not an actual protocol in the implementation, treat it as a logical **Unified Context Provider** abstraction.

---

## 5.1 Vehicle Master Data Service

Architecture note:

This is an MCP/UCP composition interface over separately hosted bounded-context services, not a shared vehicle database. Vehicle identity, telematics-unit inventory, fleet data, maintenance history, and service-provider data each have an independently owned database. Domains refer to records in other domains only through opaque IDs and never use cross-database joins or foreign keys. Live vehicle state remains in the Telematics Event and Digital Twin services.

The detailed service boundaries, ownership rules, repository outline, and initial PostgreSQL migrations are documented in `docs/architecture/master-data-services.md` and `database/`.

Endpoint examples:

* `get_vehicle_profile(vehicle_id)`
* `get_vehicle_telematics_unit(vehicle_id)`
* `get_vehicle_fleet_assignment(vehicle_id)`
* `get_vehicle_service_history(vehicle_id)`
* `get_vehicle_current_state(vehicle_id)`

Returns:

* vehicle make/model/year
* telematics unit ID
* fleet ID
* service tier
* region
* odometer
* current health state
* recent maintenance events

---

## 5.2 Fleet Master Data Service

Endpoint examples:

* `get_fleet_profile(fleet_id)`
* `get_fleet_contract(fleet_id)`
* `get_fleet_sla(fleet_id)`
* `get_fleet_priority_level(fleet_id)`
* `list_vehicles_by_fleet(fleet_id)`

Returns:

* fleet customer profile
* contract level
* SLA rules
* escalation contacts
* operating regions
* vehicle count
* priority designation

---

## 5.3 Telematics Event Service

Endpoint examples:

* `get_recent_vehicle_events(vehicle_id, window)`
* `get_event_details(event_id)`
* `search_events_by_type(event_type, window)`
* `search_events_by_region(region, window)`
* `get_active_alerts(vehicle_id)`

Returns:

* recent telemetry stream
* diagnostic trouble codes
* event frequency
* alert history
* connectivity status
* geospatial event clusters

---

## 5.4 Digital Twin Context Service

Endpoint examples:

* `get_vehicle_operational_state(vehicle_id)`
* `get_fleet_operational_state(fleet_id)`
* `get_related_entities(entity_id)`
* `get_downstream_impact(event_id)`
* `get_dependency_graph(entity_id)`

Returns:

* vehicle state
* fleet state
* affected entities
* dependencies
* active incidents
* downstream risk

---

## 5.5 Policy and Playbook Service

Endpoint examples:

* `search_playbooks(query)`
* `get_policy(policy_id)`
* `get_escalation_rules(event_type, severity)`
* `get_action_eligibility(action_type, risk_level)`
* `get_required_approval(action_type)`

Returns:

* relevant SOPs
* escalation policy
* approval requirements
* action constraints
* business rules

---

## 5.6 Prior Incident Search Service

Endpoint examples:

* `search_similar_incidents(event_signature)`
* `get_incident_resolution(incident_id)`
* `get_common_resolution_patterns(event_type)`
* `get_historical_resolution_time(event_type)`

Returns:

* similar incidents
* past resolutions
* success/failure patterns
* time-to-resolution statistics
* recurrence indicators

---

## 5.7 Risk Scoring Service

Endpoint examples:

* `calculate_event_risk(event_id)`
* `calculate_sla_risk(vehicle_id, fleet_id)`
* `calculate_safety_risk(event_id)`
* `calculate_customer_impact(event_id)`
* `calculate_composite_priority(event_id)`

Returns:

* risk score
* priority score
* component scores
* explanation factors
* confidence level

---

## 5.8 Ticketing / Case Management Service

Endpoint examples:

* `create_service_case(vehicle_id, recommendation)`
* `update_case(case_id, status)`
* `assign_case(case_id, team)`
* `attach_agent_summary(case_id, summary)`
* `get_case_status(case_id)`

Returns:

* case ID
* assigned owner
* case status
* audit reference
* workflow state

---

## 5.9 Notification Service

Endpoint examples:

* `draft_fleet_notification(fleet_id, event_id)`
* `send_internal_notification(team_id, message)`
* `send_fleet_manager_notification(fleet_id, message)`
* `get_notification_status(notification_id)`

Controls:

* customer-facing messages require approval
* internal notifications may be automated
* high-severity notifications require audit record

---

## 5.10 Approval Service

Endpoint examples:

* `request_human_approval(action)`
* `get_approval_status(approval_id)`
* `record_approval_decision(approval_id, decision)`
* `list_pending_approvals(user_id)`

Returns:

* approval ID
* reviewer
* decision status
* comments
* timestamp
* audit trail

---

## 5.11 Audit and Observability Service

Endpoint examples:

* `record_agent_trace(trace_event)`
* `record_tool_call(tool_call)`
* `record_policy_decision(policy_decision)`
* `record_recommendation(recommendation)`
* `record_human_decision(decision)`
* `get_trace(trace_id)`

Captures:

* prompts
* tool calls
* retrieved context
* model outputs
* validation results
* policy decisions
* approvals
* final actions

---

# 6. Agent Architecture and Deployment

## 6.1 Recommended Architecture

Use a controlled multi-agent architecture rather than an overly complex multi-agent design.

Recommended pattern:

* one primary orchestrator
* specialist skills/tools
* deterministic policy gate
* human approval workflow
* separate evaluation and observability layer

Logical flow:

```text
Synthetic Event Stream
        ↓
Event Ingestion
        ↓
Fleet Digital Twin
        ↓
Agent Orchestrator
        ↓
Input Guardrails
        ↓
Context Retrieval
        ↓
Contextual Prioritization
        ↓
Recommendation Generation
        ↓
Policy Gate
        ↓
Human Approval or Bounded Execution
        ↓
Audit / Observability / Feedback
```

---

## 6.2 Agent Components

### Agent Orchestrator

Responsibilities:

* receives events
* determines workflow path
* invokes skills
* manages state
* calls tools
* routes to policy gate
* returns recommendation/action

Recommended implementation:

* LangGraph for explicit workflow state
* or Google ADK for GCP-aligned agent deployment
* or OpenAI Agents SDK for simpler implementation

For portfolio value, LangGraph or ADK may provide the strongest architecture story.

---

### Triage Agent

Responsibilities:

* classify event
* determine severity
* identify missing context
* decide whether to retrieve additional information

---

### Context Agent

Responsibilities:

* retrieve playbooks
* retrieve prior incidents
* retrieve vehicle/fleet state
* construct context bundle
* flag stale or conflicting context

---

### Prioritization Agent

Responsibilities:

* rank exception
* calculate business impact
* explain priority
* identify top contributing factors

---

### Recommendation Agent

Responsibilities:

* propose next action
* generate alternatives
* explain tradeoffs
* cite relevant policy/playbook/history

---

### Policy Gate

Responsibilities:

* determine action eligibility
* enforce risk tier
* require human approval where needed
* block unsafe actions
* validate final output
* record policy decision

This component should use deterministic logic where possible.

---

### Human-in-the-Loop Interface

Responsibilities:

* show event context
* show recommendation
* show evidence
* show risk tier
* collect approval/rejection
* capture reviewer feedback

This can be built as:

* Streamlit UI
* simple React app
* FastAPI backend with basic dashboard

---

## 6.3 Deployment Architecture

Recommended local-first architecture:

* Python services
* FastAPI APIs
* LangGraph or ADK orchestration
* SQLite/Postgres for master data and audit
* Chroma, FAISS, or pgvector for vector search
* Streamlit or React for UI
* Docker Compose for local deployment

Optional cloud deployment:

* Cloud Run or Kubernetes
* Pub/Sub or Kafka-compatible event stream
* Postgres / Cloud SQL
* BigQuery for analytics
* Vertex AI or OpenAI model endpoint
* OpenTelemetry traces
* Langfuse, Phoenix, or similar tracing layer

---

# 7. Evals and Guardrail Components

## 7.1 Input Guardrails

Purpose:

Validate incoming events, user requests, and tool inputs before the agent acts.

Checks:

* required fields present
* valid vehicle ID
* valid event type
* timestamp sanity
* location bounds
* schema validation
* malformed payload detection
* duplicate event detection
* unsupported event type
* suspicious prompt injection in text fields
* PII/secrets detection in unstructured inputs

---

## 7.2 Context Quality Guardrails

Purpose:

Validate whether the retrieved context is suitable for recommendation.

Checks:

* relevant playbook retrieved
* source freshness
* no conflicting policies
* enough incident history
* context not stale
* retrieval confidence threshold
* grounding coverage
* source attribution available

---

## 7.3 Output Guardrails

Purpose:

Validate generated recommendations before they are shown or used.

Checks:

* valid JSON or Pydantic schema
* required fields present
* no unsupported claims
* action is allowed
* confidence score present
* evidence included
* no unsafe recommendation
* escalation requirement satisfied
* customer-facing text requires approval
* high-risk action blocked without approval

---

## 7.4 Tool-Call Guardrails

Purpose:

Control how agents use MCP/UCP tools.

Checks:

* tool exists
* tool allowed for current agent
* user/action authorized
* arguments match schema
* action risk tier verified
* idempotency key present for state-changing calls
* approval token present for restricted action
* tool result validated before reuse

---

## 7.5 Evals

Evaluation categories:

### Functional Evals

* correct event classification
* correct severity assignment
* correct tool selection
* correct context retrieval
* correct recommendation category
* correct routing decision

### Safety Evals

* blocks unsafe action
* detects missing approval
* prevents unauthorized tool call
* rejects malformed output
* escalates high-risk event
* avoids customer-facing action without approval

### Grounding Evals

* recommendation supported by retrieved context
* cites relevant playbook
* cites similar incident
* does not invent policy
* flags insufficient context

### Business Logic Evals

* safety events ranked higher than low-priority events
* high-priority fleet gets appropriate SLA handling
* repeated failures trigger escalation
* low-confidence cases route to human review
* allowed low-risk actions execute automatically

### Regression Evals

* rerun known scenarios after prompt changes
* rerun known scenarios after tool changes
* rerun known scenarios after model changes
* compare output stability and correctness

---

## 7.6 Metrics

Track metrics across the full control loop.

Input metrics:

* event validation failure rate
* duplicate event rate
* unsupported event type rate
* malformed payload rate

Context metrics:

* retrieval hit rate
* stale context rate
* conflicting context rate
* missing playbook rate
* context confidence score

Output metrics:

* malformed recommendation rate
* unsupported claim rate
* missing evidence rate
* policy violation rate
* low-confidence recommendation rate

Tool metrics:

* tool-call failure rate
* unauthorized tool-call attempt rate
* retry rate
* latency
* state-changing action count

Human approval metrics:

* approval rate
* rejection rate
* escalation rate
* average approval time
* most common rejection reason

Business metrics:

* time to triage
* time to route
* recommendation acceptance rate
* false escalation rate
* reduction in manual context gathering
* incident resolution time

---

# 8. Synthetic Data Generation Tasks

## 8.1 Synthetic Master Data Generation

Create synthetic master data for the telematics environment.

Entities:

### Vehicles

Fields:

* vehicle_id
* make
* model
* year
* VIN-like synthetic identifier
* fuel type or powertrain
* odometer
* region
* assigned fleet
* telematics unit ID
* service status
* warranty status
* priority level

### Telematics Units

Fields:

* unit_id
* firmware version
* activation date
* network carrier
* connectivity state
* last heartbeat
* supported capabilities
* remote command eligibility

### Fleets

Fields:

* fleet_id
* customer name
* industry
* fleet size
* contract tier
* SLA level
* operating regions
* escalation contact
* preferred service provider

### Drivers or Operators

Optional fields:

* driver_id
* assigned vehicle
* operating region
* shift schedule
* safety score
* recent alerts

### Service Providers

Fields:

* provider_id
* region
* service capabilities
* average response time
* capacity
* preferred fleet coverage

### Policies and Playbooks

Synthetic documents:

* battery degradation policy
* connectivity troubleshooting playbook
* safety incident escalation guide
* remote diagnostics approval policy
* firmware update failure playbook
* fleet SLA policy
* customer notification policy

### Incident History

Fields:

* incident_id
* vehicle_id
* fleet_id
* event type
* symptoms
* root cause
* resolution
* time to resolve
* escalation path
* outcome
* lessons learned

---

## 8.2 Synthetic Error Types

Create realistic but generic telematics event/error categories.

Examples:

* low battery voltage
* repeated battery voltage drop
* engine diagnostic trouble code
* emissions system warning
* brake system warning
* tire pressure warning
* harsh braking
* harsh acceleration
* rapid deceleration
* connectivity loss
* intermittent LTE connection
* GPS drift
* remote command failure
* firmware update failure
* missed heartbeat
* sensor data anomaly
* excessive idling
* geofence violation
* unauthorized movement
* safety alert
* crash-like event
* service overdue
* repeated fault recurrence

Each error type should include:

* severity range
* normal frequency
* false-positive likelihood
* required context
* likely action
* approval requirement
* SLA sensitivity

---

## 8.3 Artificial Data Streaming

Build a synthetic streaming simulator for telematics data.

Stream types:

### Vehicle Health Stream

Fields:

* vehicle_id
* timestamp
* diagnostic codes
* battery voltage
* engine temperature
* tire pressure
* odometer
* fuel or charge level
* warning flags

### Vehicle State Stream

Fields:

* vehicle_id
* timestamp
* ignition state
* speed
* movement state
* door state
* trip state
* service mode

### Connectivity Stream

Fields:

* vehicle_id
* timestamp
* signal strength
* carrier
* connection state
* last heartbeat
* message delivery latency
* remote command success/failure

### Geolocation Stream

Fields:

* vehicle_id
* timestamp
* latitude
* longitude
* heading
* speed
* geofence ID
* region
* route deviation

### Safety Event Stream

Fields:

* vehicle_id
* timestamp
* event type
* severity
* acceleration/deceleration
* location
* driver/operator ID
* airbag-like signal flag
* crash-likelihood score

### Remote Command Stream

Fields:

* vehicle_id
* timestamp
* command type
* command status
* failure reason
* retry count
* requesting user/system
* approval status

### Firmware / OTA Stream

Fields:

* vehicle_id
* timestamp
* firmware version
* update status
* error code
* rollback state
* retry count

---

## 8.4 Streaming Simulation Requirements

The artificial stream should support:

* normal operation
* random noise
* recurring issues
* burst events
* regional outages
* fleet-specific incidents
* device-specific failures
* correlated multi-signal events
* gradual degradation patterns
* sudden safety alerts
* delayed or out-of-order events
* duplicate events
* missing events
* stale events

This is important because real operational systems rarely receive clean, perfectly ordered data.

---

# 9. Build Roadmap

## Phase 1: Foundation

Tasks:

* define domain model
* generate synthetic master data
* generate synthetic playbooks
* build event schema
* build SQLite/Postgres storage
* build basic event ingestion API
* build simple streaming simulator

Deliverable:

> Synthetic telematics data platform with master data, events, and playbooks.

---

## Phase 2: Digital Twin and Prioritization

Tasks:

* build fleet digital twin state model
* update state from event stream
* implement deterministic priority score
* classify exceptions
* create basic exception dashboard

Deliverable:

> Command-center view showing vehicle events, active incidents, priority score, and impacted fleet.

---

## Phase 3: RAG and Tools

Tasks:

* create vector index over playbooks and prior incidents
* build MCP/UCP-style tool endpoints
* implement context retrieval
* implement similar-incident search
* add source citations to recommendations

Deliverable:

> Agent can retrieve vehicle state, fleet context, playbooks, policies, and prior incidents.

---

## Phase 4: Agentic Workflow

Tasks:

* implement agent orchestrator
* implement triage skill
* implement contextual prioritization skill
* implement recommendation skill
* implement policy gate
* generate structured recommendation output

Deliverable:

> Agent can triage an exception, gather context, recommend action, and explain rationale.

---

## Phase 5: HITL and Bounded Execution

Tasks:

* build approval UI
* implement approval workflow
* classify action risk
* allow low-risk automated actions
* block high-risk actions without approval
* create mock ticket/service case actions

Deliverable:

> Controlled action workflow with human approval and audit trail.

---

## Phase 6: Evals, Guardrails, and Observability

Tasks:

* implement input validation
* implement output schema validation
* implement tool-call validation
* implement policy tests
* build scenario evals
* add tracing
* log retrieved context, tool calls, recommendations, approvals, and actions
* build simple metrics dashboard

Deliverable:

> Production-control layer demonstrating validation, evaluation, observability, and auditability.

---

## Phase 7: Portfolio Packaging

Tasks:

* write README
* create architecture diagram
* record demo video
* publish technical article
* publish LinkedIn summary
* create resume bullet
* publish sanitized GitHub repo

Deliverable:

> Public portfolio artifact demonstrating production-grade agentic AI architecture using synthetic telematics data.

---

# 10. Recommended MVP Scope

The MVP should avoid overbuilding.

Minimum viable scope:

* 100 synthetic vehicles
* 5 synthetic fleets
* 8–10 event types
* 3 synthetic playbooks
* 20 prior incidents
* event stream simulator
* digital twin state table
* priority scoring
* one agent orchestrator
* 5–6 tools
* structured recommendations
* policy gate
* human approval for high-risk actions
* basic audit log
* 10 eval scenarios

The MVP should prove the architecture, not the completeness of the telematics domain.

---

# 11. Success Criteria

The project is successful if it demonstrates that an agentic AI system can:

* ingest synthetic operational events
* update an operational state model
* retrieve relevant context
* prioritize exceptions
* recommend next actions
* validate outputs
* enforce policy gates
* route high-risk actions for approval
* execute low-risk mock actions
* capture audit trails
* support evaluation and observability

The most important proof point:

> The system shows how AI moves a command center from passive visibility to governed decision support and bounded action.

---

# 12. Portfolio Narrative

Public narrative:

> FleetOps AI Control Lab is a synthetic telematics command-center simulation that demonstrates production-grade agentic AI patterns. It uses synthetic vehicle, fleet, telemetry, policy, and incident data to model how AI can support exception triage, contextual prioritization, recommendation, human approval, and controlled execution. The project focuses on architecture patterns rather than proprietary domain data.

Resume-friendly bullet:

> Built a synthetic telematics AI control lab demonstrating multi-agent orchestration, RAG over playbooks and prior incidents, MCP-style tool integration, contextual prioritization, HITL approval, output validation, observability, and policy-based bounded execution using synthetic fleet and telemetry data.

Interview framing:

> I chose telematics because it is a signal-heavy operational domain with real-time events, diagnostic signals, safety concerns, service workflows, and escalation policies. The project demonstrates how agentic AI can operate safely in complex enterprise environments without using employer data or proprietary systems.
