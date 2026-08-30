from argparse import Namespace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from fleetops_runtime import load_service_app
from scripts import seed_synthetic_tenant


ROOT = Path(__file__).resolve().parents[1]


def test_seeder_is_api_only_reproducible_and_idempotent(monkeypatch) -> None:
    clients = {
        "http://tenant": TestClient(
            load_service_app(ROOT / "services" / "tenant-master")
        ),
        "http://vehicle": TestClient(
            load_service_app(ROOT / "services" / "vehicle-master")
        ),
        "http://unit": TestClient(
            load_service_app(ROOT / "services" / "telematics-unit-master")
        ),
        "http://fleet": TestClient(
            load_service_app(ROOT / "services" / "fleet-master")
        ),
        "http://provider": TestClient(
            load_service_app(ROOT / "services" / "service-provider-master")
        ),
    }

    def post(
        url: str,
        payload: dict[str, Any],
        idempotency_key: str,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        parsed = urlsplit(url)
        client = clients[f"{parsed.scheme}://{parsed.netloc}"]
        headers = {"Idempotency-Key": idempotency_key}
        if tenant_id:
            headers["X-Tenant-ID"] = tenant_id
        response = client.post(parsed.path, json=payload, headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    monkeypatch.setattr(seed_synthetic_tenant, "post", post)
    args = Namespace(
        seed=42,
        tenant_slug="reproducible-demo",
        fleets=2,
        vehicles=6,
        tenant_url="http://tenant",
        vehicle_url="http://vehicle",
        unit_url="http://unit",
        fleet_url="http://fleet",
        provider_url="http://provider",
    )

    first = seed_synthetic_tenant.seed(args)
    second = seed_synthetic_tenant.seed(args)
    assert second == first

    headers = {"X-Tenant-ID": first["tenantId"]}
    assert (
        len(clients["http://fleet"].get("/v1/fleets", headers=headers).json()["items"])
        == 2
    )
    assert (
        len(
            clients["http://vehicle"]
            .get("/v1/vehicles", headers=headers)
            .json()["items"]
        )
        == 6
    )
    assert (
        len(
            clients["http://unit"]
            .get("/v1/telematics-units", headers=headers)
            .json()["items"]
        )
        == 6
    )
