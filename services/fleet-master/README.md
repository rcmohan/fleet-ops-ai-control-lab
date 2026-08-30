# Fleet Master Service

Owns synthetic customer/fleet identity, contract classification, SLA classification, operating regions, priority, and escalation contacts.

This directory owns its FastAPI application, domain models, PostgreSQL migrations, tests, generated OpenAPI document, and boundary documentation. Synthetic records are created through the service API.

Implemented operations:

- `get_fleet_profile(fleet_id)`
- `get_fleet_contract(fleet_id)`
- `get_fleet_sla(fleet_id)`
- `get_fleet_priority_level(fleet_id)`
- `list_fleets(filters)`
- `create_fleet(profile)`
- `update_fleet(fleet_id, changes)`
- `replace_operating_regions(fleet_id, regions)`
- `replace_escalation_contacts(fleet_id, contacts)`

Vehicle membership is discovered through the Vehicle Master API; this service does not query the vehicle database.
