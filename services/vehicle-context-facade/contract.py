from fleetops_runtime import Operation, Parameter, ServiceContract


PROFILE = {
    "vehicleId": "veh_demo_001",
    "make": "Nova",
    "model": "Transit-E",
    "modelYear": 2026,
    "fleetId": "flt_demo_001",
    "telematicsUnitId": "tcu_demo_001",
}

CONTRACT = ServiceContract(
    slug="vehicle-context-facade",
    title="Vehicle Context Facade",
    description="Read-only MCP/UCP composition of authoritative vehicle-related domain APIs.",
    operations=(
        Operation(
            method="GET",
            path="/v1/vehicle-context/{vehicle_id}/profile",
            operation_id="getVehicleProfile",
            summary="Get authoritative vehicle profile context",
            response={
                **PROFILE,
                "vehicleId": "{vehicle_id}",
                "source": "vehicle-master",
            },
        ),
        Operation(
            method="GET",
            path="/v1/vehicle-context/{vehicle_id}/telematics-unit",
            operation_id="getVehicleTelematicsUnit",
            summary="Get the assigned telematics unit context",
            response={
                "vehicleId": "{vehicle_id}",
                "unitId": "tcu_demo_001",
                "firmwareVersion": "3.4.1",
                "source": "telematics-unit-master",
            },
        ),
        Operation(
            method="GET",
            path="/v1/vehicle-context/{vehicle_id}/fleet-assignment",
            operation_id="getVehicleFleetAssignment",
            summary="Get fleet assignment context",
            response={
                "vehicleId": "{vehicle_id}",
                "fleetId": "flt_demo_001",
                "customerName": "Northstar Synthetic Logistics",
                "source": "fleet-master",
            },
        ),
        Operation(
            method="GET",
            path="/v1/vehicle-context/{vehicle_id}/service-history",
            operation_id="getVehicleServiceHistory",
            summary="Get composed service history",
            response={
                "vehicleId": "{vehicle_id}",
                "items": [{"maintenanceId": "mtn_demo_001", "status": "completed"}],
                "partial": False,
            },
            parameters=(Parameter("cursor"), Parameter("limit", schema_type="integer")),
        ),
        Operation(
            method="GET",
            path="/v1/vehicle-context/{vehicle_id}/current-state",
            operation_id="getVehicleCurrentState",
            summary="Get current digital-twin state",
            response={
                "vehicleId": "{vehicle_id}",
                "healthState": "healthy",
                "odometerKm": 15000.0,
                "observedAt": "2026-08-22T12:00:00Z",
                "source": "digital-twin-context",
            },
        ),
        Operation(
            method="GET",
            path="/v1/vehicle-context/{vehicle_id}",
            operation_id="getVehicleContext",
            summary="Get a composed vehicle context bundle",
            response={
                "vehicleId": "{vehicle_id}",
                "profile": PROFILE,
                "fleet": {"fleetId": "flt_demo_001"},
                "telematicsUnit": {"unitId": "tcu_demo_001"},
                "operationalState": {"healthState": "healthy"},
                "unavailableDependencies": [],
            },
            parameters=(
                Parameter("include", description="Comma-separated context sections"),
            ),
        ),
    ),
)
