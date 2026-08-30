from typing import Any

from fastapi import FastAPI, Header, Query

from fleetops_runtime.service_support import (
    MasterDataStore,
    create_service_app,
    dump_model,
    normalize_codes,
    paged,
)

from .models import CoverageRequest, LifecycleRequest, ProviderCreate, ProviderPatch
from .seed_data import SERVICE_PROVIDERS


def create_app() -> FastAPI:
    app = create_service_app(
        slug="service-provider-master",
        title="Service Provider Master Service",
        description=(
            "Authoritative synthetic provider directory, coverage, "
            "capabilities, and capacity."
        ),
    )
    store = MasterDataStore(SERVICE_PROVIDERS)

    @app.get(
        "/v1/service-providers/{provider_id}",
        operation_id="getServiceProvider",
    )
    def get_provider(provider_id: str) -> dict[str, Any]:
        return store.get(provider_id)

    @app.get("/v1/service-providers", operation_id="listServiceProviders")
    def list_providers(
        region: str | None = None,
        capability: str | None = None,
        lifecycle_status: str | None = None,
        cursor: str | None = None,
        limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        items = sorted(store.list(), key=lambda item: item["providerId"])
        if region:
            items = [item for item in items if region in item["regions"]]
        if capability:
            items = [item for item in items if capability in item["capabilities"]]
        if lifecycle_status:
            items = [
                item for item in items
                if item["lifecycleStatus"] == lifecycle_status
            ]
        return paged(items, cursor, limit)

    @app.post("/v1/service-providers", operation_id="createServiceProvider")
    def create_provider(
        body: ProviderCreate,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        data = dump_model(body)
        data["regions"] = normalize_codes(data["regions"], "regions")
        data["capabilities"] = normalize_codes(
            data["capabilities"], "capabilities"
        )
        return store.create("sp", "providerId", data, None, idempotency_key)

    @app.patch(
        "/v1/service-providers/{provider_id}",
        operation_id="updateServiceProvider",
    )
    def update_provider(
        provider_id: str,
        body: ProviderPatch,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        changes = dump_model(body, exclude_unset=True)
        return store.mutate(
            provider_id,
            f"patch:{provider_id}",
            idempotency_key,
            lambda record: record.update(changes),
        )

    @app.put(
        "/v1/service-providers/{provider_id}/status",
        operation_id="setServiceProviderStatus",
    )
    def set_status(
        provider_id: str,
        body: LifecycleRequest,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return store.mutate(
            provider_id,
            f"status:{provider_id}",
            idempotency_key,
            lambda record: record.update(lifecycleStatus=body.status),
        )

    @app.put(
        "/v1/service-providers/{provider_id}/coverage",
        operation_id="replaceServiceProviderCoverage",
    )
    def replace_coverage(
        provider_id: str,
        body: CoverageRequest,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        regions = normalize_codes(body.regions, "regions")
        capabilities = normalize_codes(body.capabilities, "capabilities")
        record = store.mutate(
            provider_id,
            f"coverage:{provider_id}",
            idempotency_key,
            lambda item: item.update(
                regions=regions,
                capabilities=capabilities,
            ),
        )
        return {
            key: record[key]
            for key in (
                "providerId", "regions", "capabilities", "sourceVersion"
            )
        }

    return app
