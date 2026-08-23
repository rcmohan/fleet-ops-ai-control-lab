from fleetops_runtime import Operation, ServiceContract


CONTRACT = ServiceContract(
    slug="digital-twin-context",
    title="Digital Twin Context Service",
    description="Derived point-in-time vehicle and fleet operational state.",
    operations=(
        Operation("GET", "/v1/digital-twins/vehicles/{vehicle_id}", "getVehicleOperationalState", "Get vehicle operational state", {"vehicleId": "{vehicle_id}", "healthState": "healthy", "connectivityState": "connected", "odometerKm": 15000.0, "activeIncidentIds": [], "observedAt": "2026-08-22T12:00:00Z", "sourceVersion": 7}),
        Operation("GET", "/v1/digital-twins/fleets/{fleet_id}", "getFleetOperationalState", "Get fleet operational state", {"fleetId": "{fleet_id}", "vehicleCount": 100, "healthyVehicleCount": 96, "warningVehicleCount": 4, "criticalVehicleCount": 0, "observedAt": "2026-08-22T12:00:00Z"}),
        Operation("GET", "/v1/digital-twins/entities/{entity_id}/related", "getRelatedEntities", "Get logically related entities", {"entityId": "{entity_id}", "relatedEntities": [{"entityId": "veh_demo_001", "entityType": "vehicle", "relationship": "member"}]}),
        Operation("GET", "/v1/digital-twins/events/{event_id}/downstream-impact", "getDownstreamImpact", "Get downstream event impact", {"eventId": "{event_id}", "affectedVehicleIds": ["veh_demo_001"], "affectedFleetIds": ["flt_demo_001"], "riskLevel": "low", "summary": "Synthetic limited impact"}),
        Operation("GET", "/v1/digital-twins/entities/{entity_id}/dependency-graph", "getDependencyGraph", "Get entity dependency graph", {"rootEntityId": "{entity_id}", "nodes": [{"entityId": "veh_demo_001", "entityType": "vehicle"}], "edges": []}),
        Operation("POST", "/v1/digital-twins/events", "applyOperationalEvent", "Apply an event to the digital twin", {"eventId": "evt_demo_001", "stateVersion": 8, "status": "applied"}, {"eventId": "evt_demo_001", "vehicleId": "veh_demo_001", "eventType": "battery_voltage", "observedAt": "2026-08-22T12:00:00Z", "payload": {"voltage": 11.8}}),
    ),
)

