# Application Services

Each child folder is an independently owned application/domain boundary. Every service contains:

- `contract.py`: routes, parameters, and example requests and responses.
- `handlers.py`: the implementation of each operation in the contract, including request validation and business rules.
- `openapi.json`: the generated OpenAPI 3.1 document.
- `README.md`: ownership and boundary notes.

The shared runtime in `fleetops_runtime/` turns a contract and its handlers into a FastAPI app. It provides the PostgreSQL pool and migrations, one database transaction per request, `Idempotency-Key` replay for POST requests, a transactional outbox for messages to other services, typed errors, and calls to other services. Without `handlers.py`, the runtime serves the contract's examples instead (stub mode); the contract tests use this.

## Run all services

Set `POSTGRES_PASSWORD` in `.env`, then:

```powershell
docker compose up --build
```

Compose starts PostgreSQL (`db`) first, creates any missing service databases (`db-bootstrap`), and holds the services until it is healthy (see `database/README.md`). Set `FLEETOPS_DB_HOST` and `FLEETOPS_DB_PORT` to use another server. Each service creates and migrates its own schema on startup, and `/health/ready` reports `503` while its database is unreachable.

Each API exposes:

- Swagger UI at `/docs`
- OpenAPI at `/openapi.json`
- Liveness at `/health/live`
- Readiness at `/health/ready`

Ports are assigned from `8101` through `8116` in `compose.yaml` in catalog order, bound to `127.0.0.1`. The `gateway` service also serves every API on `http://127.0.0.1:8080/<service>/`, for example `http://127.0.0.1:8080/approval/docs`, and shows a health and latency page at `http://127.0.0.1:8080/` with the last hour of checks made by `status-monitor`.

## Run one service locally

```powershell
$env:FLEETOPS_SERVICE_PATH = "services/approval"
$env:FLEETOPS_DB_HOST = "localhost"
$env:FLEETOPS_APPROVAL_URL = "http://localhost:8114"   # FLEETOPS_<SERVICE>_URL for each service it calls
uvicorn service_app:app --reload --port 8114
```

Regenerate checked-in OpenAPI documents after changing a contract or a handler's request model:

```powershell
python scripts/export_openapi.py
```

## Service catalog

| Domain folder | Responsibility | Calls |
| --- | --- | --- |
| `vehicle-master` | Vehicle identity, lifecycle, fleet and telematics-unit assignment | fleet-master, telematics-unit-master |
| `telematics-unit-master` | Telematics device inventory, firmware, remote-command eligibility | |
| `fleet-master` | Fleet/customer, contract, SLA, regions, escalation contacts | service-provider-master |
| `maintenance-history` | Vehicle maintenance records with append-only corrections | vehicle-master, service-provider-master |
| `service-provider-master` | Service-provider directory, coverage, capacity | |
| `vehicle-context-facade` | Read-only composition of vehicle context; no database | five services it composes |
| `telematics-event` | Event ingestion, severity rules, active alerts | vehicle-master; outbox to digital-twin-context and signal-correlation |
| `digital-twin-context` | Current vehicle and fleet state derived from events | vehicle-master, fleet-master |
| `policy-playbook` | Policies, playbook search, escalation rules, action controls | |
| `incident-search` | Resolved incident history, similarity search, statistics | |
| `risk-scoring` | Explainable `risk-v1` scores; no database | telematics-event, vehicle-master, fleet-master, digital-twin-context |
| `case-management` | Service cases, assignment, status workflow, attachments | vehicle-master; outbox to incident-search |
| `notification` | Drafts and simulated delivery; fleet-manager messages need an approval | fleet-master, telematics-event, approval |
| `approval` | Approval requests, expiry, reviewer decisions | |
| `audit-observability` | Append-only audit events and trace retrieval | |
| `signal-correlation` | Correlation rules over signals; incidents scored, policy-checked, and turned into cases (after approval when policy requires it) | risk-scoring, policy-playbook, approval, case-management; outbox to audit-observability |

## Boundary rules

- Each service owns its contracts and data; no service reads another service's database.
- References to other domains are opaque IDs. Writes that set one check it exists through the owning service's API.
- Messages that must not be lost (events to the digital twin and correlation, resolved cases to incident search, audit records) go through the sender's outbox and are retried until delivered.
- Every POST accepts an optional `Idempotency-Key` header; a retry with the same key and body returns the original response.
- Errors return `{"detail": {"code": ..., "message": ...}}`. A down dependency returns `503 DEPENDENCY_UNAVAILABLE`.
- There is no authentication yet. The approval service trusts the `X-Reviewer-Id` header and checks it against its reviewer list, so keep the services bound to `127.0.0.1`.
- Notification delivery is simulated: nothing leaves the lab.
