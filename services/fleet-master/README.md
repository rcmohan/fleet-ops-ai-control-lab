# Fleet Master Service

Owns synthetic customer/fleet identity, contract classification, SLA classification, operating regions, priority, and escalation contacts.

Planned operations:

- `get_fleet_profile(fleet_id)`
- `get_fleet_contract(fleet_id)`
- `get_fleet_sla(fleet_id)`
- `get_fleet_priority_level(fleet_id)`
- `list_fleets(filters)`

Vehicle membership is discovered through the Vehicle Master API; this service does not query the vehicle database.

