from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query

from fleetops_runtime.service_support import (
    TenantId,
    create_document_store,
    create_service_app,
    dump_model,
    paged,
)

from .models import (
    FleetAssignment,
    LifecycleRequest,
    UnitAssignment,
    VehicleCreate,
    VehiclePatch,
)


def create_app() -> FastAPI:
    app = create_service_app(
        slug="vehicle-master",
        title="Vehicle Master Service",
        description=(
            "Authoritative vehicle identity, specifications, lifecycle, "
            "and assignment references."
        ),
    )
    store = create_document_store(Path(__file__).parent)

    @app.get("/v1/vehicles/{vehicle_id}", operation_id="getVehicleProfile")
    def get_vehicle(vehicle_id: str, tenant_id: TenantId) -> dict[str, Any]:
        return store.get(tenant_id, vehicle_id)

    @app.get("/v1/vehicles", operation_id="listVehiclesByFleet")
    def list_vehicles(
        tenant_id: TenantId,
        fleet_id: str | None = None,
        region: str | None = None,
        lifecycle_status: str | None = None,
        cursor: str | None = None,
        limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        items = sorted(store.list(tenant_id), key=lambda item: item["vehicleId"])
        if fleet_id:
            items = [item for item in items if item.get("fleetId") == fleet_id]
        if region:
            items = [item for item in items if item["regionCode"] == region]
        if lifecycle_status:
            items = [
                item for item in items if item["lifecycleStatus"] == lifecycle_status
            ]
        return paged(items, cursor, limit)

    @app.post("/v1/vehicles", operation_id="createVehicle")
    def create_vehicle(
        body: VehicleCreate,
        tenant_id: TenantId,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        data = dump_model(body)
        data["lifecycleStatus"] = "active"
        return store.create(
            tenant_id, "veh", "vehicleId", data, "syntheticVin", idempotency_key
        )

    @app.patch("/v1/vehicles/{vehicle_id}", operation_id="updateVehicleProfile")
    def update_vehicle(
        vehicle_id: str,
        body: VehiclePatch,
        tenant_id: TenantId,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        changes = dump_model(body, exclude_unset=True)
        return store.mutate(
            tenant_id,
            vehicle_id,
            f"patch:{vehicle_id}",
            idempotency_key,
            lambda record: record.update(changes),
        )

    @app.put(
        "/v1/vehicles/{vehicle_id}/lifecycle-status",
        operation_id="setVehicleLifecycleStatus",
    )
    def set_lifecycle(
        vehicle_id: str,
        body: LifecycleRequest,
        tenant_id: TenantId,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return store.mutate(
            tenant_id,
            vehicle_id,
            f"lifecycle:{vehicle_id}",
            idempotency_key,
            lambda record: record.update(lifecycleStatus=body.status),
        )

    @app.put(
        "/v1/vehicles/{vehicle_id}/fleet-assignment",
        operation_id="assignVehicleToFleet",
    )
    def assign_fleet(
        vehicle_id: str,
        body: FleetAssignment,
        tenant_id: TenantId,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        record = store.mutate(
            tenant_id,
            vehicle_id,
            f"fleet:{vehicle_id}",
            idempotency_key,
            lambda value: value.update(fleetId=body.fleet_id),
        )
        return {key: record[key] for key in ("vehicleId", "fleetId", "sourceVersion")}

    @app.put(
        "/v1/vehicles/{vehicle_id}/telematics-unit-assignment",
        operation_id="assignTelematicsUnit",
    )
    def assign_unit(
        vehicle_id: str,
        body: UnitAssignment,
        tenant_id: TenantId,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        if body.telematics_unit_id and any(
            item.get("telematicsUnitId") == body.telematics_unit_id
            and item["vehicleId"] != vehicle_id
            for item in store.list(tenant_id)
        ):
            raise HTTPException(409, "telematicsUnitId is already assigned")
        record = store.mutate(
            tenant_id,
            vehicle_id,
            f"unit:{vehicle_id}",
            idempotency_key,
            lambda value: value.update(telematicsUnitId=body.telematics_unit_id),
        )
        return {
            key: record[key]
            for key in ("vehicleId", "telematicsUnitId", "sourceVersion")
        }

    return app
