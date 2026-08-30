from pathlib import Path

from fastapi.testclient import TestClient

from fleetops_runtime import load_service_app


SERVICE = Path(__file__).resolve().parents[1]


def test_provider_filters_coverage() -> None:
    client = TestClient(load_service_app(SERVICE))
    created = client.post(
        "/v1/service-providers",
        json={
            "providerName": "Synthetic West Workshop",
            "regions": ["us-west"],
            "capabilities": ["battery"],
            "dailyCapacity": 8,
        },
    ).json()
    results = client.get(
        "/v1/service-providers",
        params={"region": "us-west", "capability": "battery"},
    ).json()
    assert [item["providerId"] for item in results["items"]] == [
        created["providerId"]
    ]
    invalid = client.put(
        f"/v1/service-providers/{created['providerId']}/status",
        json={"status": "busy"},
    )
    assert invalid.status_code == 422
