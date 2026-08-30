from pathlib import Path

from fastapi.testclient import TestClient

from fleetops_runtime import load_service_app


SERVICE = Path(__file__).resolve().parents[1]


def test_vehicle_crud_filtering_and_unassignment() -> None:
    client = TestClient(load_service_app(SERVICE))
    tenant_headers = {"X-Tenant-ID": "ten_test_alpha"}
    payload = {
        "syntheticVin": "SYNTH-TEST-VEHICLE-01",
        "make": "Nova",
        "model": "Courier",
        "modelYear": 2025,
        "powertrainType": "hybrid",
        "regionCode": "us-west",
        "fleetId": "flt_test_001",
    }

    created = client.post(
        "/v1/vehicles",
        json=payload,
        headers={**tenant_headers, "Idempotency-Key": "vehicle-create-1"},
    )
    assert created.status_code == 200
    vehicle = created.json()
    assert vehicle["vehicleId"].startswith("veh_")
    replay = client.post(
        "/v1/vehicles",
        json=payload,
        headers={**tenant_headers, "Idempotency-Key": "vehicle-create-1"},
    )
    assert replay.json() == vehicle
    assert (
        client.post("/v1/vehicles", json=payload, headers=tenant_headers).status_code
        == 409
    )

    listed = client.get(
        "/v1/vehicles",
        params={"fleet_id": "flt_test_001"},
        headers=tenant_headers,
    ).json()
    assert [item["vehicleId"] for item in listed["items"]] == [vehicle["vehicleId"]]

    updated = client.patch(
        f"/v1/vehicles/{vehicle['vehicleId']}",
        json={"priorityLevel": "critical"},
        headers=tenant_headers,
    ).json()
    assert updated["priorityLevel"] == "critical"
    assert updated["sourceVersion"] == 2

    unassigned = client.put(
        f"/v1/vehicles/{vehicle['vehicleId']}/fleet-assignment",
        json={"fleetId": None},
        headers=tenant_headers,
    ).json()
    assert unassigned["fleetId"] is None
    assert (
        client.get("/v1/vehicles/not-present", headers=tenant_headers).status_code
        == 404
    )
    assert (
        client.get(
            f"/v1/vehicles/{vehicle['vehicleId']}",
            headers={"X-Tenant-ID": "ten_test_beta"},
        ).status_code
        == 404
    )
    assert client.get(f"/v1/vehicles/{vehicle['vehicleId']}").status_code == 422
