from fleetops_runtime import Operation, ServiceContract


CONTRACT = ServiceContract(
    slug="digital-twin-context",
    title="Digital Twin Context Service",
    description="Derived point-in-time vehicle and fleet operational state.",
    operations=(
        Operation(
            method="GET",
            path="/v1/digital-twins/vehicles/{vehicle_id}",
            operation_id="getVehicleOperationalState",
            summary="Get vehicle operational state",
            response={
                "vehicleId": "{vehicle_id}",
                "fleetId": "flt_demo_001",
                "healthState": "warning",
                "connectivityState": "connected",
                "odometerKm": 15000.0,
                "batteryVoltage": 11.6,
                "lastLocation": {"latitude": 40.71, "longitude": -74.0, "speedKph": 0},
                "activeIssues": [
                    {
                        "issue": "battery",
                        "severity": "warning",
                        "since": "2026-08-22T12:00:00Z",
                        "eventId": "evt_demo_001",
                    }
                ],
                "observedAt": "2026-08-22T12:00:00Z",
                "sourceVersion": 7,
            },
        ),
        Operation(
            method="GET",
            path="/v1/digital-twins/fleets/{fleet_id}",
            operation_id="getFleetOperationalState",
            summary="Get fleet operational state",
            response={
                "fleetId": "{fleet_id}",
                "vehicleCount": 100,
                "healthyVehicleCount": 96,
                "warningVehicleCount": 4,
                "criticalVehicleCount": 0,
                "observedAt": "2026-08-22T12:00:00Z",
            },
        ),
        Operation(
            method="GET",
            path="/v1/digital-twins/entities/{entity_id}/related",
            operation_id="getRelatedEntities",
            summary="Get logically related entities",
            response={
                "entityId": "{entity_id}",
                "relatedEntities": [
                    {
                        "entityId": "flt_demo_001",
                        "entityType": "fleet",
                        "relationship": "member_of",
                    }
                ],
            },
        ),
        Operation(
            method="GET",
            path="/v1/digital-twins/events/{event_id}/downstream-impact",
            operation_id="getDownstreamImpact",
            summary="Get downstream event impact",
            response={
                "eventId": "{event_id}",
                "affectedVehicleIds": ["veh_demo_001"],
                "affectedFleetIds": ["flt_demo_001"],
                "riskLevel": "low",
                "summary": "Synthetic limited impact",
            },
        ),
        Operation(
            method="GET",
            path="/v1/digital-twins/entities/{entity_id}/dependency-graph",
            operation_id="getDependencyGraph",
            summary="Get entity dependency graph",
            response={
                "rootEntityId": "{entity_id}",
                "nodes": [
                    {"entityId": "veh_demo_001", "entityType": "vehicle"},
                    {"entityId": "flt_demo_001", "entityType": "fleet"},
                ],
                "edges": [
                    {"from": "veh_demo_001", "to": "flt_demo_001", "relationship": "member_of"}
                ],
            },
        ),
        Operation(
            method="POST",
            path="/v1/digital-twins/events",
            operation_id="applyOperationalEvent",
            summary="Apply an event to the digital twin",
            response={
                "eventId": "evt_demo_001",
                "stateVersion": 8,
                "status": "applied",
            },
            request={
                "eventId": "evt_demo_001",
                "vehicleId": "veh_demo_001",
                "eventType": "battery_voltage",
                "severity": "warning",
                "observedAt": "2026-08-22T12:00:00Z",
                "payload": {"voltage": 11.6},
            },
        ),
    ),
)
