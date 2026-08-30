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

The independently deployable FastAPI services live under `services/`. The vehicle, fleet, telematics-unit, and service-provider master-data APIs implement validated stateful behavior over synthetic records. Transactional and operational domains remain contract stubs with deterministic synthetic responses.

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
docker compose up --build
```

Swagger UI is available on `/docs` for every running service. Compose maps Tenant Master to `8100` and the remaining services to `8101` through `8115`; see `services/README.md` for the catalog and local-run instructions.

Seed a reproducible tenant after the master services are healthy:

```powershell
python scripts/seed_synthetic_tenant.py --seed 20260829
```
