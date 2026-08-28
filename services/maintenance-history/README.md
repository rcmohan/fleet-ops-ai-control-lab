# Maintenance History Service

Owns append-oriented vehicle service and maintenance records.

The dummy FastAPI endpoints are defined in `contract.py`; the generated API document is `openapi.json`.

Implemented operations:

- `get_vehicle_service_history(vehicle_id, page)`
- `get_maintenance_record(maintenance_id)`
- `record_maintenance_event(event)`
- `correct_maintenance_record(maintenance_id, correction)`

`vehicle_id` and `service_provider_id` are opaque external references with no database foreign keys.
