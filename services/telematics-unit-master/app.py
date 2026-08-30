from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Query

from fleetops_runtime.service_support import (
    TenantId,
    create_document_store,
    create_service_app,
    dump_model,
    normalize_codes,
    paged,
)

from .models import (
    CapabilitiesRequest,
    EligibilityRequest,
    FirmwareRequest,
    LifecycleRequest,
    TelematicsUnitCreate,
    TelematicsUnitPatch,
)


def create_app() -> FastAPI:
    app = create_service_app(
        slug="telematics-unit-master",
        title="Telematics Unit Master Service",
        description=(
            "Authoritative telematics hardware inventory and capability metadata."
        ),
    )
    store = create_document_store(Path(__file__).parent)

    @app.get("/v1/telematics-units/{unit_id}", operation_id="getTelematicsUnit")
    def get_unit(unit_id: str, tenant_id: TenantId) -> dict[str, Any]:
        return store.get(tenant_id, unit_id)

    @app.get("/v1/telematics-units", operation_id="listTelematicsUnits")
    def list_units(
        tenant_id: TenantId,
        lifecycle_status: str | None = None,
        capability: str | None = None,
        cursor: str | None = None,
        limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        items = sorted(store.list(tenant_id), key=lambda item: item["unitId"])
        if lifecycle_status:
            items = [
                item for item in items if item["lifecycleStatus"] == lifecycle_status
            ]
        if capability:
            items = [item for item in items if capability in item["capabilities"]]
        return paged(items, cursor, limit)

    @app.post("/v1/telematics-units", operation_id="createTelematicsUnit")
    def create_unit(
        body: TelematicsUnitCreate,
        tenant_id: TenantId,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        data = dump_model(body)
        data["capabilities"] = normalize_codes(data["capabilities"], "capabilities")
        return store.create(
            tenant_id, "tcu", "unitId", data, "serialNumber", idempotency_key
        )

    @app.patch("/v1/telematics-units/{unit_id}", operation_id="updateTelematicsUnit")
    def update_unit(
        unit_id: str,
        body: TelematicsUnitPatch,
        tenant_id: TenantId,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        changes = dump_model(body, exclude_unset=True)
        return store.mutate(
            tenant_id,
            unit_id,
            f"patch:{unit_id}",
            idempotency_key,
            lambda record: record.update(changes),
        )

    @app.put(
        "/v1/telematics-units/{unit_id}/firmware",
        operation_id="updateFirmwareInventory",
    )
    def update_firmware(
        unit_id: str,
        body: FirmwareRequest,
        tenant_id: TenantId,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return store.mutate(
            tenant_id,
            unit_id,
            f"firmware:{unit_id}",
            idempotency_key,
            lambda record: record.update(firmwareVersion=body.firmware_version),
        )

    @app.put(
        "/v1/telematics-units/{unit_id}/lifecycle-status",
        operation_id="setTelematicsUnitLifecycleStatus",
    )
    def set_lifecycle(
        unit_id: str,
        body: LifecycleRequest,
        tenant_id: TenantId,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return store.mutate(
            tenant_id,
            unit_id,
            f"lifecycle:{unit_id}",
            idempotency_key,
            lambda record: record.update(lifecycleStatus=body.status),
        )

    @app.put(
        "/v1/telematics-units/{unit_id}/remote-command-eligibility",
        operation_id="setRemoteCommandEligibility",
    )
    def set_eligibility(
        unit_id: str,
        body: EligibilityRequest,
        tenant_id: TenantId,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return store.mutate(
            tenant_id,
            unit_id,
            f"eligibility:{unit_id}",
            idempotency_key,
            lambda record: record.update(remoteCommandEligibility=body.eligibility),
        )

    @app.put(
        "/v1/telematics-units/{unit_id}/capabilities",
        operation_id="replaceTelematicsUnitCapabilities",
    )
    def replace_capabilities(
        unit_id: str,
        body: CapabilitiesRequest,
        tenant_id: TenantId,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        capabilities = normalize_codes(body.capabilities, "capabilities")
        record = store.mutate(
            tenant_id,
            unit_id,
            f"capabilities:{unit_id}",
            idempotency_key,
            lambda item: item.update(capabilities=capabilities),
        )
        return {key: record[key] for key in ("unitId", "capabilities", "sourceVersion")}

    return app
