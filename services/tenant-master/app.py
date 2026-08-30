from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Query

from fleetops_runtime.service_support import (
    create_document_store,
    create_service_app,
    dump_model,
    paged,
)

from .models import TenantCreate, TenantPatch


SYSTEM_SCOPE = "tenant-directory"


def create_app() -> FastAPI:
    app = create_service_app(
        slug="tenant-master",
        title="Tenant Master Service",
        description="Authoritative tenant identity and lifecycle directory.",
    )
    store = create_document_store(Path(__file__).parent)

    @app.get("/v1/tenants/{tenant_id}", operation_id="getTenant")
    def get_tenant(tenant_id: str) -> dict[str, Any]:
        return store.get(SYSTEM_SCOPE, tenant_id)

    @app.get("/v1/tenants", operation_id="listTenants")
    def list_tenants(
        lifecycle_status: str | None = None,
        cursor: str | None = None,
        limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        items = sorted(store.list(SYSTEM_SCOPE), key=lambda item: item["tenantId"])
        if lifecycle_status:
            items = [
                item for item in items if item["lifecycleStatus"] == lifecycle_status
            ]
        return paged(items, cursor, limit)

    @app.post("/v1/tenants", operation_id="createTenant")
    def create_tenant(
        body: TenantCreate,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return store.create(
            SYSTEM_SCOPE,
            "ten",
            "tenantId",
            dump_model(body),
            "slug",
            idempotency_key,
        )

    @app.patch("/v1/tenants/{tenant_id}", operation_id="updateTenant")
    def update_tenant(
        tenant_id: str,
        body: TenantPatch,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        changes = dump_model(body, exclude_unset=True)
        return store.mutate(
            SYSTEM_SCOPE,
            tenant_id,
            f"patch:{tenant_id}",
            idempotency_key,
            lambda record: record.update(changes),
        )

    return app
