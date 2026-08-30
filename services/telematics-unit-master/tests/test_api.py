from pathlib import Path

from fastapi.testclient import TestClient

from fleetops_runtime import load_service_app


SERVICE = Path(__file__).resolve().parents[1]


def test_unit_inventory_and_capability_validation() -> None:
    client = TestClient(load_service_app(SERVICE))
    headers = {"X-Tenant-ID": "ten_test_alpha"}
    created = client.post(
        "/v1/telematics-units",
        json={
            "serialNumber": "TCU-SYNTH-TEST-02",
            "hardwareModel": "NX-Lite",
            "firmwareVersion": "1.0.0",
            "capabilities": ["LOCATION", "diagnostics"],
        },
        headers=headers,
    ).json()
    assert created["unitId"].startswith("tcu_")
    assert created["capabilities"] == ["location", "diagnostics"]

    response = client.put(
        f"/v1/telematics-units/{created['unitId']}/capabilities",
        json={"capabilities": ["location", "location"]},
        headers=headers,
    )
    assert response.status_code == 422
