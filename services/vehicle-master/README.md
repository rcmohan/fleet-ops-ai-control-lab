# Vehicle Master Service

Owns stable vehicle identity, factory/specification attributes, lifecycle status, and the current fleet/device reference IDs.

The dummy FastAPI endpoints are defined in `contract.py`; the generated API document is `openapi.json`.

Implemented operations:

- `get_vehicle_profile(vehicle_id)`
- `create_vehicle(profile)`
- `update_vehicle_profile(vehicle_id, changes)`
- `set_vehicle_lifecycle_status(vehicle_id, status)`
- `assign_vehicle_to_fleet(vehicle_id, fleet_id)`
- `assign_telematics_unit(vehicle_id, telematics_unit_id)`

`fleet_id` and `telematics_unit_id` are opaque references. This service neither joins to nor writes the Fleet Master or Telematics Unit Master databases.
