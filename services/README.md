# Application Service Contracts

Each child folder is an independently owned application/domain boundary. Every service contains:

- `contract.py` — route definitions, request data objects, response data objects, and deterministic dummy values.
- `openapi.json` — generated OpenAPI 3.1 contract.
- `README.md` — ownership and boundary notes.

The shared FastAPI runtime in `fleetops_runtime/` turns each contract into a runnable API. The services intentionally perform no persistence or downstream calls yet.

## Run all services

```powershell
docker compose up --build
```

Each API exposes:

- Swagger UI at `/docs`
- OpenAPI at `/openapi.json`
- Liveness at `/health/live`
- Readiness at `/health/ready`

Ports are assigned from `8101` through `8115` in `compose.yaml` in catalog order.

## Run one service locally

```powershell
$env:FLEETOPS_SERVICE_PATH = "services/approval"
uvicorn service_app:app --reload --port 8114
```

Regenerate checked-in OpenAPI documents after changing a contract:

```powershell
python scripts/export_openapi.py
```

Identifiers are opaque strings issued by the owning service. A signature containing another domain's ID does not create data ownership or a database foreign key.

## Service catalog

| Domain folder | Responsibility |
| --- | --- |
| `vehicle-master` | Vehicle identity and lifecycle |
| `telematics-unit-master` | Telematics device inventory |
| `fleet-master` | Fleet/customer, contract, SLA, region, and contact data |
| `maintenance-history` | Vehicle maintenance records |
| `service-provider-master` | Service-provider directory |
| `vehicle-context-facade` | Read-only composition of vehicle context |
| `telematics-event` | Telemetry events and alerts |
| `digital-twin-context` | Derived operational state and dependencies |
| `policy-playbook` | Policy, playbook, eligibility, and approval rules |
| `incident-search` | Prior-incident retrieval and aggregate patterns |
| `risk-scoring` | Safety, SLA, customer-impact, and priority scoring |
| `case-management` | Operational service cases |
| `notification` | Drafted and delivered notifications |
| `approval` | Human approval workflow |
| `audit-observability` | Agent, policy, tool, recommendation, and decision traces |

## Boundary rules

- Each service owns its contracts and data; no service reads another service's database.
- Cross-domain composition occurs through service calls or event-driven projections.
- Mutating operations will require an idempotency key when persistence is implemented.
- Authentication and authorization are not implemented in the dummy services.
- Request bodies are validated against generated Pydantic data objects; dummy responses are deterministic.
- Database adapters, event publishing, downstream composition, and production error models remain implementation work.
