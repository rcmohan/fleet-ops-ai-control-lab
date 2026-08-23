from fleetops_runtime import Operation, Parameter, ServiceContract


VEHICLE = {
    "vehicleId": "veh_demo_001",
    "syntheticVin": "SYNTH000000000001",
    "make": "Nova",
    "model": "Transit-E",
    "modelYear": 2026,
    "powertrainType": "battery_electric",
    "regionCode": "us-east",
    "lifecycleStatus": "active",
    "serviceStatus": "in_service",
    "warrantyStatus": "active",
    "priorityLevel": "standard",
    "fleetId": "flt_demo_001",
    "telematicsUnitId": "tcu_demo_001",
    "sourceVersion": 1,
}

CONTRACT = ServiceContract(
    slug="vehicle-master",
    title="Vehicle Master Service",
    description="Authoritative vehicle identity, specifications, lifecycle, and assignment references.",
    operations=(
        Operation("GET", "/v1/vehicles/{vehicle_id}", "getVehicleProfile", "Get a vehicle profile", {**VEHICLE, "vehicleId": "{vehicle_id}"}),
        Operation("POST", "/v1/vehicles", "createVehicle", "Create a synthetic vehicle", VEHICLE, {"syntheticVin": "SYNTH000000000001", "make": "Nova", "model": "Transit-E", "modelYear": 2026, "powertrainType": "battery_electric", "regionCode": "us-east"}),
        Operation("PATCH", "/v1/vehicles/{vehicle_id}", "updateVehicleProfile", "Update vehicle-owned profile fields", {**VEHICLE, "vehicleId": "{vehicle_id}", "sourceVersion": 2}, {"regionCode": "us-east", "priorityLevel": "high"}),
        Operation("PUT", "/v1/vehicles/{vehicle_id}/lifecycle-status", "setVehicleLifecycleStatus", "Set vehicle lifecycle status", {**VEHICLE, "vehicleId": "{vehicle_id}", "lifecycleStatus": "inactive", "sourceVersion": 2}, {"status": "inactive"}),
        Operation("PUT", "/v1/vehicles/{vehicle_id}/fleet-assignment", "assignVehicleToFleet", "Assign or unassign a fleet ID", {"vehicleId": "{vehicle_id}", "fleetId": "flt_demo_001", "sourceVersion": 2}, {"fleetId": "flt_demo_001"}),
        Operation("PUT", "/v1/vehicles/{vehicle_id}/telematics-unit-assignment", "assignTelematicsUnit", "Assign or unassign a telematics unit ID", {"vehicleId": "{vehicle_id}", "telematicsUnitId": "tcu_demo_001", "sourceVersion": 2}, {"telematicsUnitId": "tcu_demo_001"}),
        Operation("GET", "/v1/vehicles", "listVehiclesByFleet", "List vehicles referencing a fleet", {"items": [VEHICLE], "nextCursor": ""}, parameters=(Parameter("fleet_id", description="Opaque Fleet Master ID"), Parameter("cursor"), Parameter("limit", schema_type="integer"))),
    ),
)

