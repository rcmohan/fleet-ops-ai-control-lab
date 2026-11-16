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

python -m pip install -r requirements-dev.txt
python -m pytest -q                            # Postgres tests need FLEETOPS_TEST_DATABASE_URL
```

Swagger UI is available on `/docs` for every running service. Compose maps the services to localhost ports `8101` through `8115`, and a gateway on `http://127.0.0.1:8080` shows a live status page and serves each one at `/<service>/` (for example `/approval/docs`); see `services/README.md` for the catalog and local-run instructions.
