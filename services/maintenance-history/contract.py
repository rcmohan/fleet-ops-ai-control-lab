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
        Operation("GET", "/v1/maintenance-records/{maintenance_id}", "getMaintenanceRecord", "Get a maintenance record", {**RECORD, "maintenanceId": "{maintenance_id}"}),
        Operation("GET", "/v1/vehicles/{vehicle_id}/maintenance-records", "getVehicleServiceHistory", "Get vehicle service history", {"items": [{**RECORD, "vehicleId": "{vehicle_id}"}], "nextCursor": ""}, parameters=(Parameter("cursor"), Parameter("limit", schema_type="integer"))),
        Operation("POST", "/v1/maintenance-records", "recordMaintenanceEvent", "Record a maintenance event", RECORD, {"vehicleId": "veh_demo_001", "serviceProviderId": "sp_demo_001", "eventType": "preventive", "serviceStatus": "completed", "openedAt": "2026-08-01T09:00:00Z", "summary": "Synthetic scheduled inspection"}),
        Operation("POST", "/v1/maintenance-records/{maintenance_id}/corrections", "correctMaintenanceRecord", "Append a maintenance correction", {**RECORD, "maintenanceId": "{maintenance_id}", "sourceVersion": 2}, {"reason": "Synthetic data correction", "changes": {"odometerKm": 15000.0}}),
    ),
)

