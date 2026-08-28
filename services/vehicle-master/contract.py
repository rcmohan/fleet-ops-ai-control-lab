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
        Operation(
            method="GET",
            path="/v1/vehicles/{vehicle_id}",
            operation_id="getVehicleProfile",
            summary="Get a vehicle profile",
            response={**VEHICLE, "vehicleId": "{vehicle_id}"},
        ),
        Operation(
            method="POST",
            path="/v1/vehicles",
            operation_id="createVehicle",
            summary="Create a synthetic vehicle",
            response=VEHICLE,
            request={
                "syntheticVin": "SYNTH000000000001",
                "make": "Nova",
                "model": "Transit-E",
                "modelYear": 2026,
                "powertrainType": "battery_electric",
                "regionCode": "us-east",
            },
        ),
        Operation(
            method="PATCH",
            path="/v1/vehicles/{vehicle_id}",
            operation_id="updateVehicleProfile",
            summary="Update vehicle-owned profile fields",
            response={**VEHICLE, "vehicleId": "{vehicle_id}", "sourceVersion": 2},
            request={"regionCode": "us-east", "priorityLevel": "high"},
        ),
        Operation(
            method="PUT",
            path="/v1/vehicles/{vehicle_id}/lifecycle-status",
            operation_id="setVehicleLifecycleStatus",
            summary="Set vehicle lifecycle status",
            response={
                **VEHICLE,
                "vehicleId": "{vehicle_id}",
                "lifecycleStatus": "inactive",
                "sourceVersion": 2,
            },
            request={"status": "inactive"},
        ),
        Operation(
            method="PUT",
            path="/v1/vehicles/{vehicle_id}/fleet-assignment",
            operation_id="assignVehicleToFleet",
            summary="Assign or unassign a fleet ID",
            response={
                "vehicleId": "{vehicle_id}",
                "fleetId": "flt_demo_001",
                "sourceVersion": 2,
            },
            request={"fleetId": "flt_demo_001"},
        ),
        Operation(
            method="PUT",
            path="/v1/vehicles/{vehicle_id}/telematics-unit-assignment",
            operation_id="assignTelematicsUnit",
            summary="Assign or unassign a telematics unit ID",
            response={
                "vehicleId": "{vehicle_id}",
                "telematicsUnitId": "tcu_demo_001",
                "sourceVersion": 2,
            },
            request={"telematicsUnitId": "tcu_demo_001"},
        ),
        Operation(
            method="GET",
            path="/v1/vehicles",
            operation_id="listVehiclesByFleet",
            summary="List vehicles referencing a fleet",
            response={"items": [VEHICLE], "nextCursor": ""},
            parameters=(
                Parameter("fleet_id", description="Opaque Fleet Master ID"),
                Parameter("cursor"),
                Parameter("limit", schema_type="integer"),
            ),
        ),
    ),
)
