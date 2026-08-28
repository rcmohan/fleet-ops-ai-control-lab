from fleetops_runtime import Operation, Parameter, ServiceContract


RECORD = {
    "maintenanceId": "mtn_demo_001",
    "vehicleId": "veh_demo_001",
    "serviceProviderId": "sp_demo_001",
    "eventType": "preventive",
    "serviceStatus": "completed",
    "openedAt": "2026-08-01T09:00:00Z",
    "completedAt": "2026-08-01T11:00:00Z",
    "odometerKm": 15000.0,
    "summary": "Synthetic scheduled inspection",
    "resolution": "No defects found",
    "sourceVersion": 1,
}

CONTRACT = ServiceContract(
    slug="maintenance-history",
    title="Maintenance History Service",
    description="Append-oriented synthetic vehicle maintenance and service history.",
    operations=(
        Operation(
            method="GET",
            path="/v1/maintenance-records/{maintenance_id}",
            operation_id="getMaintenanceRecord",
            summary="Get a maintenance record",
            response={**RECORD, "maintenanceId": "{maintenance_id}"},
        ),
        Operation(
            method="GET",
            path="/v1/vehicles/{vehicle_id}/maintenance-records",
            operation_id="getVehicleServiceHistory",
            summary="Get vehicle service history",
            response={
                "items": [{**RECORD, "vehicleId": "{vehicle_id}"}],
                "nextCursor": "",
            },
            parameters=(Parameter("cursor"), Parameter("limit", schema_type="integer")),
        ),
        Operation(
            method="POST",
            path="/v1/maintenance-records",
            operation_id="recordMaintenanceEvent",
            summary="Record a maintenance event",
            response=RECORD,
            request={
                "vehicleId": "veh_demo_001",
                "serviceProviderId": "sp_demo_001",
                "eventType": "preventive",
                "serviceStatus": "completed",
                "openedAt": "2026-08-01T09:00:00Z",
                "summary": "Synthetic scheduled inspection",
            },
        ),
        Operation(
            method="POST",
            path="/v1/maintenance-records/{maintenance_id}/corrections",
            operation_id="correctMaintenanceRecord",
            summary="Append a maintenance correction",
            response={
                **RECORD,
                "maintenanceId": "{maintenance_id}",
                "sourceVersion": 2,
            },
            request={
                "reason": "Synthetic data correction",
                "changes": {"odometerKm": 15000.0},
            },
        ),
    ),
)
