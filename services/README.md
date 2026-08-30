# Application Service Contracts

Each child folder is an independently owned application/domain boundary. Every service contains a generated `openapi.json` and ownership `README.md`.

Implemented master-data services additionally own:

- `app.py` — FastAPI routes and application behavior.
- `models.py` — domain-specific request models and validation.
- `migrations/` — service-owned PostgreSQL schema history.
- `tests/` — service-owned API and tenant-isolation tests.

The other services retain a `contract.py` that the shared runtime turns into deterministic simulation endpoints. This compatibility path is temporary and is not used by the implemented master-data services.

## Run all services

```powershell
docker compose up --build
```

Each API exposes:

- Swagger UI at `/docs`
- OpenAPI at `/openapi.json`
- Liveness at `/health/live`
- Readiness at `/health/ready`

Tenant Master uses port `8100`; the original catalog uses `8101` through `8115`.

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
| `tenant-master` | Tenant identity and lifecycle |
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
- Master-data mutations accept an optional `Idempotency-Key` header and replay the first result for the same operation and key.
- Authentication and authorization are not implemented in the dummy services.
- Master-data request bodies use explicit Pydantic domain models; non-master dummy responses remain deterministic.
- Compose-backed master-data state is durable in a separate logical PostgreSQL database per service. Without `DATABASE_URL`, tests use a tenant-scoped process-local adapter.
- The four domain services require `X-Tenant-ID`; Compose verifies that tenant through Tenant Master before accessing data.
- Synthetic data is created only through service APIs by `scripts/seed_synthetic_tenant.py`.
- Database adapters, event publishing, downstream composition, and production error models remain implementation work.
