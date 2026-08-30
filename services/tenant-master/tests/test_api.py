from pathlib import Path

from fastapi.testclient import TestClient

from fleetops_runtime import load_service_app


SERVICE = Path(__file__).resolve().parents[1]


def test_tenant_creation_is_deterministic_and_idempotent() -> None:
    client = TestClient(load_service_app(SERVICE))
    payload = {"slug": "demo-tenant", "displayName": "Demo Tenant"}
    headers = {"Idempotency-Key": "seed:demo-tenant"}

    created = client.post("/v1/tenants", json=payload, headers=headers)
    assert created.status_code == 200
    tenant = created.json()
    assert tenant["tenantId"].startswith("ten_")
    assert client.post("/v1/tenants", json=payload, headers=headers).json() == tenant
