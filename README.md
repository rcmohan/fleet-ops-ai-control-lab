# fleet-ops-ai-control-lab

FleetOps AI Control Lab is a synthetic telematics command-center simulation designed to demonstrate production-grade agentic AI patterns.

The goal is not to build a toy chatbot over vehicle data. The goal is to show how an enterprise AI system can ingest operational signals, maintain contextual state, prioritize exceptions, use tools, retrieve knowledge, recommend actions, enforce guardrails, and support human-in-the-loop decision-making.

The project should demonstrate:

agentic AI architecture
synthetic data generation
streaming event processing
operational digital twin modeling
contextual prioritization
RAG over playbooks and incident history
MCP/UCP-style tool integration
human approval workflows
output validation
evaluation harnesses
observability and auditability
bounded autonomous execution

The entire project should use synthetic data only. It should not use data, code, architecture, APIs, or business rules from any existing solutions.

## Dummy application services

The 16 independently deployable FastAPI services live under `services/`. Fourteen store their data in their own PostgreSQL database; risk scoring and the vehicle context facade compute their answers from the other services. See `services/README.md` for what each one does and `database/README.md` for the databases.

```powershell
# .env must set POSTGRES_PASSWORD (git ignores .env)
docker compose up --build                      # PostgreSQL, the services, and the gateway
python -m fleetops_seed load                   # synthetic master data from seed/seed-v1
python -m fleetops_sim --minutes 60           # fleet movement and telemetry for the last hour

python -m pip install -r requirements-dev.txt
python -m pytest -q                            # Postgres tests need FLEETOPS_TEST_DATABASE_URL
```

Swagger UI is available on `/docs` for every running service. Compose maps the services to localhost ports `8101` through `8116`, and a gateway on `http://127.0.0.1:8080` serves each one at `/<service>/` (for example `/approval/docs`); see `services/README.md` for the catalog and local-run instructions.

The gateway's front page is a status page. The `status-monitor` service (`status_monitor/`) checks every service's readiness every 5 seconds, whether or not the page is open, and keeps the last hour in memory. The page loads that hour when it opens and then follows new checks. History starts over when the monitor restarts.

## Simulator

`python -m fleetops_sim` plays the fleet as telematics devices. Each active vehicle drives trips inside its region and parks between them. Trips follow a small road network per region (`fleetops_sim/roads.py`): real town locations joined along highway corridors, so vehicles stay on land and only cross water on bridges and tunnels. `tests/test_roads.py` checks the networks against a land mask. It reports:

- location, speed, and odometer while driving
- ignition on/off at the start and end of each trip
- a heartbeat every 5 minutes
- a battery reading every 15 minutes, with a few weak batteries that sag below the warning line
- rare faults: harsh braking, diagnostic codes, and connectivity drops

It reads the vehicle list from vehicle-master and resumes each vehicle from its last state in the digital twin. Events go to telematics-event, which raises alerts and forwards them to the twin.

```powershell
python -m fleetops_sim --minutes 60                       # replay the last hour as fast as possible
python -m fleetops_sim --minutes 15 --live                # then keep running in real time (Ctrl+C)
python -m fleetops_sim --inject battery_connectivity:veh_golden_001@20
```

`--inject` scripts the MVP incident on one vehicle at the given minute: a battery reading below 11.8 V, then a missed heartbeat, then a critical diagnostic code, all within 12 minutes. Other options: `--max-vehicles`, `--tick-seconds`, `--late-share` (out-of-order delivery), `--seed`.

## Incident response without agents

`signal-correlation` turns that pattern into a service case with deterministic code only:

1. telematics-event forwards every warning or critical event to it through the outbox.
2. Each arriving signal re-runs rule `battery-connectivity-v1` over that vehicle's signals around it, so late events still complete the pattern. A match becomes an incident. While a vehicle has an open incident, repeats are added to it as evidence.
3. A background worker scores the incident with risk-scoring, then asks policy-playbook whether `create_service_case` is allowed at that risk level.
4. If allowed, it opens the case. Otherwise it requests an approval and waits for the decision: approved opens the case, rejected or expired does not.

Every step is on the incident's timeline and in the audit trail under one trace ID. The console below shows all of it; the same calls by hand:

```powershell
curl http://127.0.0.1:8080/signal-correlation/v1/correlation/incidents
curl http://127.0.0.1:8080/approval/v1/approvals?reviewer_id=reviewer_ops_001
curl -X POST http://127.0.0.1:8080/approval/v1/approvals/<approvalId>/decisions `
     -H "X-Reviewer-Id: reviewer_ops_001" -H "Content-Type: application/json" `
     -d '{"decision": "approved"}'
curl http://127.0.0.1:8080/audit-observability/v1/traces/<traceId>
```

## Consoles

`docker compose up` also starts the operations console at `http://127.0.0.1:8501` (Streamlit, in `console/`):

- **Incidents**: every correlated incident with its status, risk and policy decision. For each one: the approval (approve or reject with a comment), the service case (assign, move through its workflow, resolve), the timeline, the trigger and supporting events, the vehicle's profile, twin state and alerts, and the audit trail.
- **Approvals**: requests waiting for the selected reviewer's role, each linked to its incident.
- **Simulate**: injects the battery-connectivity fault for a vehicle, ending just before now.

The **fleet console** at `http://127.0.0.1:8080/fleet/` (Streamlit, in `fleet_console/`, served through the gateway) is read-only:

- **Fleets**: each fleet's contract, SLA, priority and regions, with live counts of healthy, warning, critical and stale vehicles and open incidents. A selected fleet shows its preferred service provider, its vehicles, and a map.
- **Vehicles**: every vehicle, filterable by fleet, region, lifecycle and health. A selected vehicle shows its profile, telematics unit, twin state, alerts, last 24 hours of events, maintenance history, and incidents, which link to the operations console.
- **Map**: every vehicle at its last known position, coloured by health. A vehicle is stale after 15 minutes without a report.

In the operations console, the browser never calls the services. The console's server side does, and it sends the reviewer identity itself, only for reviewers in `FLEETOPS_CONSOLE_REVIEWERS` (default: `reviewer_ops_001`, `reviewer_safety_001`). There is no login, so anyone who can open the console can act as those reviewers; keep it on `127.0.0.1`. To run it outside Compose:

```powershell
python -m pip install -r requirements-console.txt
$env:FLEETOPS_CONSOLE_GATEWAY = "http://127.0.0.1:8080"
python -m streamlit run console/app.py
```
