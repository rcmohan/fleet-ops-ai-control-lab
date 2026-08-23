from fleetops_runtime import Operation, Parameter, ServiceContract


PROFILE = {"vehicleId": "veh_demo_001", "make": "Nova", "model": "Transit-E", "modelYear": 2026, "fleetId": "flt_demo_001", "telematicsUnitId": "tcu_demo_001"}

CONTRACT = ServiceContract(
    slug="vehicle-context-facade",
    title="Vehicle Context Facade",
    description="Read-only MCP/UCP composition of authoritative vehicle-related domain APIs.",
    operations=(
        Operation("GET", "/v1/vehicle-context/{vehicle_id}/profile", "getVehicleProfile", "Get authoritative vehicle profile context", {**PROFILE, "vehicleId": "{vehicle_id}", "source": "vehicle-master"}),
        Operation("GET", "/v1/vehicle-context/{vehicle_id}/telematics-unit", "getVehicleTelematicsUnit", "Get the assigned telematics unit context", {"vehicleId": "{vehicle_id}", "unitId": "tcu_demo_001", "firmwareVersion": "3.4.1", "source": "telematics-unit-master"}),
        Operation("GET", "/v1/vehicle-context/{vehicle_id}/fleet-assignment", "getVehicleFleetAssignment", "Get fleet assignment context", {"vehicleId": "{vehicle_id}", "fleetId": "flt_demo_001", "customerName": "Northstar Synthetic Logistics", "source": "fleet-master"}),
        Operation("GET", "/v1/vehicle-context/{vehicle_id}/service-history", "getVehicleServiceHistory", "Get composed service history", {"vehicleId": "{vehicle_id}", "items": [{"maintenanceId": "mtn_demo_001", "status": "completed"}], "partial": False}, parameters=(Parameter("cursor"), Parameter("limit", schema_type="integer"))),
        Operation("GET", "/v1/vehicle-context/{vehicle_id}/current-state", "getVehicleCurrentState", "Get current digital-twin state", {"vehicleId": "{vehicle_id}", "healthState": "healthy", "odometerKm": 15000.0, "observedAt": "2026-08-22T12:00:00Z", "source": "digital-twin-context"}),
        Operation("GET", "/v1/vehicle-context/{vehicle_id}", "getVehicleContext", "Get a composed vehicle context bundle", {"vehicleId": "{vehicle_id}", "profile": PROFILE, "fleet": {"fleetId": "flt_demo_001"}, "telematicsUnit": {"unitId": "tcu_demo_001"}, "operationalState": {"healthState": "healthy"}, "unavailableDependencies": []}, parameters=(Parameter("include", description="Comma-separated context sections"),)),
    ),
)

