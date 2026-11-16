# Service Databases

Each child directory belongs to one service and is applied only to that service's own PostgreSQL database. No service reads another service's database, and there are no cross-database foreign keys; references to other domains are opaque IDs checked through the owning service's API.

| Directory | Database | Schema |
| --- | --- | --- |
| `vehicle-master/` | `fleetops_vehicle_master` | `master_data` |
| `telematics-unit-master/` | `fleetops_telematics_unit_master` | `master_data` |
| `fleet-master/` | `fleetops_fleet_master` | `master_data` |
| `maintenance-history/` | `fleetops_maintenance_history` | `master_data` |
| `service-provider-master/` | `fleetops_service_provider_master` | `master_data` |
| `telematics-event/` | `fleetops_telematics_event` | `telemetry` |
| `digital-twin-context/` | `fleetops_digital_twin_context` | `twin` |
| `policy-playbook/` | `fleetops_policy_playbook` | `policy` |
| `incident-search/` | `fleetops_incident_search` | `incidents` |
| `case-management/` | `fleetops_case_management` | `cases` |
| `notification/` | `fleetops_notification` | `notifications` |
| `approval/` | `fleetops_approval` | `approvals` |
| `audit-observability/` | `fleetops_audit_observability` | `audit` |

`risk-scoring` and `vehicle-context-facade` own no data and have no database.

## Setup

With Compose, nothing is manual: the first time the `db` container starts with an empty volume, `docker-init/10-create-service-databases.sh` runs `bootstrap/create_service_databases.sql`, creating the 13 databases, each with its own login role. The roles use `POSTGRES_PASSWORD` from `.env`, which is also what the services connect with.

If the volume was initialized before that script existed, run it once by hand. It is safe to re-run:

```powershell
$password = (Select-String -Path .env -Pattern '^POSTGRES_PASSWORD=(.*)').Matches[0].Groups[1].Value
Get-Content database/bootstrap/create_service_databases.sql |
  docker exec -i fleet-ops-db psql -U postgres -d postgres -v password=$password
```

For another PostgreSQL 14+ server, run the same SQL there and set `FLEETOPS_DB_HOST`, `FLEETOPS_DB_PORT`, and `POSTGRES_PASSWORD` for the services.

## Migrations

Services apply their own migrations when they start; nothing needs to be run by hand. Files run in name order (`001_...sql`, `002_...sql`). Each file and its record in `runtime.schema_migrations` commit in one transaction, and an advisory lock stops two replicas from migrating at once, so migration files do not contain `BEGIN`/`COMMIT`.

The runtime also creates a `runtime` schema in every service database:

- `runtime.schema_migrations`: applied files and their checksums. A service refuses to start if an applied file was edited.
- `runtime.idempotency_keys`: stored responses for POST requests sent with an `Idempotency-Key` header.
- `runtime.outbox`: messages to other services, written in the same transaction as the change that caused them and delivered afterwards with retries.

Never edit a migration that has been applied anywhere; add the next numbered file instead.
