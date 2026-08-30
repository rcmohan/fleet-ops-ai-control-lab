from pathlib import Path

from fastapi.testclient import TestClient

from fleetops_runtime import load_service_app


SERVICE = Path(__file__).resolve().parents[1]


def test_fleet_owns_regions_contacts_and_sla_classification() -> None:
    client = TestClient(load_service_app(SERVICE))
    created = client.post(
        "/v1/fleets",
        json={
            "customerName": "Synthetic Test Fleet",
            "industryCode": "utilities",
            "contractTier": "premium",
            "slaLevel": "enhanced",
            "operatingRegions": ["US-WEST"],
            "escalationContacts": [
                {
                    "name": "Synthetic Contact",
                    "role": "manager",
                    "email": "test@example.invalid",
                }
            ],
        },
    ).json()
    assert created["fleetId"].startswith("flt_")
    assert created["operatingRegions"] == ["us-west"]
    assert created["escalationContacts"][0]["contactId"].startswith("contact_")
    sla = client.get(f"/v1/fleets/{created['fleetId']}/sla").json()
    assert sla["responseTargetMinutes"] == 120
