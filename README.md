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

The 15 independently deployable FastAPI services live under `services/`. Thirteen store their data in their own PostgreSQL database; risk scoring and the vehicle context facade compute their answers from the other services. See `services/README.md` for what each one does and `database/README.md` for the databases.

```powershell
# .env must set POSTGRES_PASSWORD (git ignores .env)
docker compose up --build                      # PostgreSQL, the services, and the gateway
python -m fleetops_seed load                   # synthetic master data from seed/seed-v1
python -m fleetops_sim --minutes 60           # fleet movement and telemetry for the last hour

python -m pip install -r requirements-dev.txt
python -m pytest -q                            # Postgres tests need FLEETOPS_TEST_DATABASE_URL
```

Swagger UI is available on `/docs` for every running service. Compose maps the services to localhost ports `8101` through `8115`, and a gateway on `http://127.0.0.1:8080` shows a live status page and serves each one at `/<service>/` (for example `/approval/docs`); see `services/README.md` for the catalog and local-run instructions.

## Simulator

`python -m fleetops_sim` plays the fleet as telematics devices. Each active vehicle drives trips inside its region and parks between them. It reports:

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
