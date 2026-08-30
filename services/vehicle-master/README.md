# Vehicle Master Service

Owns stable vehicle identity, factory/specification attributes, lifecycle status, and the current fleet/device reference IDs.

This directory owns its FastAPI application, domain models, PostgreSQL migrations, tests, generated OpenAPI document, and boundary documentation. Synthetic records are created through the service API.

Implemented operations:

- `get_vehicle_profile(vehicle_id)`
- `create_vehicle(profile)`
- `update_vehicle_profile(vehicle_id, changes)`
- `set_vehicle_lifecycle_status(vehicle_id, status)`
- `assign_vehicle_to_fleet(vehicle_id, fleet_id)`
- `assign_telematics_unit(vehicle_id, telematics_unit_id)`
- `list_vehicles(filters)`

`fleet_id` and `telematics_unit_id` are opaque references. This service neither joins to nor writes the Fleet Master or Telematics Unit Master databases.

Assignment request fields accept `null` to unassign. A telematics unit can be assigned to only one vehicle within this service. Records are retired through lifecycle changes rather than deleted.
