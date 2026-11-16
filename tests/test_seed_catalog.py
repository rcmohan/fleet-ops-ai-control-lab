"""The seed catalog is deterministic, internally consistent, and accepted by the services'
own request models, checked without a database."""

import json
import sys

from fleetops_seed import build_catalog
from fleetops_seed.catalog import GOLDEN_VEHICLE, REGIONS
from fleetops_seed.csvio import read_catalog, write_catalog

from conftest import ROOT, all_services

SERVICES = all_services()


def handlers(slug: str):
    return sys.modules[f"{slug.replace('-', '_')}_handlers"]


def test_same_seed_gives_identical_catalog() -> None:
    first = build_catalog(vehicles=60, fleets=6, incidents=20)
    second = build_catalog(vehicles=60, fleets=6, incidents=20)
    assert json.dumps(first.__dict__, sort_keys=True) == json.dumps(second.__dict__, sort_keys=True)
    other = build_catalog(seed_version="seed-v2", vehicles=60, fleets=6, incidents=20)
    assert other.vehicles[1] != first.vehicles[1]


def test_growing_the_catalog_keeps_existing_records() -> None:
    small = build_catalog(vehicles=50)
    large = build_catalog(vehicles=100)
    # Fleet choice depends only on the vehicle's own seed, so vehicle 1-50 are unchanged.
    assert large.vehicles[:51] == small.vehicles[:51]


def test_relationships_agree_in_both_directions() -> None:
    catalog = build_catalog()
    assert catalog.counts()["vehicles"] == 501
    fleets = {f["fleetId"]: f for f in catalog.fleets}
    units = {u["unitId"]: u for u in catalog.units}
    providers = {p["providerId"]: p for p in catalog.providers}
    vehicles = {v["vehicleId"]: v for v in catalog.vehicles}
    assert len(vehicles) == len(catalog.vehicles)
    assert len({v["syntheticVin"] for v in catalog.vehicles}) == len(catalog.vehicles)

    assigned_units = [v["telematicsUnitId"] for v in catalog.vehicles]
    assert len(set(assigned_units)) == len(assigned_units)
    for vehicle in catalog.vehicles:
        fleet = fleets[vehicle["fleetId"]]
        assert vehicle["regionCode"] in fleet["operatingRegions"]
        assert vehicle["telematicsUnitId"] in units
    for fleet in catalog.fleets:
        members = [v for v in catalog.vehicles if v["fleetId"] == fleet["fleetId"]]
        assert fleet["declaredFleetSize"] == len(members)
        assert set(fleet["operatingRegions"]) <= set(REGIONS)
        if fleet["preferredServiceProviderId"]:
            provider = providers[fleet["preferredServiceProviderId"]]
            assert fleet["operatingRegions"][0] in provider["regions"]
    for record in catalog.maintenance:
        assert record["vehicleId"] in vehicles
        assert record["completedAt"] > record["openedAt"]
    by_vehicle: dict[str, list] = {}
    for record in catalog.maintenance:
        by_vehicle.setdefault(record["vehicleId"], []).append(record)
    for records in by_vehicle.values():
        odometers = [r["odometerKm"] for r in sorted(records, key=lambda r: r["openedAt"])]
        assert odometers == sorted(odometers)
    for incident in catalog.incidents:
        assert incident["vehicleId"] in vehicles
        assert incident["resolvedAt"] >= incident["openedAt"]

    assert vehicles["veh_golden_001"] == GOLDEN_VEHICLE
    assert {i["incidentId"] for i in catalog.incidents} >= {"inc_golden_001", "inc_golden_002"}


def without_nulls(records):
    return [{k: v for k, v in record.items() if v is not None} for record in records]


def test_csv_round_trip_is_lossless(tmp_path) -> None:
    catalog = build_catalog(vehicles=80, fleets=8, incidents=30)
    write_catalog(catalog, tmp_path)
    loaded = read_catalog(tmp_path)
    assert loaded.seed_version == catalog.seed_version
    for kind in ("providers", "fleets", "units", "vehicles", "maintenance", "incidents"):
        assert without_nulls(getattr(loaded, kind)) == without_nulls(getattr(catalog, kind)), kind
    assert {k: without_nulls(v) for k, v in loaded.fleet_contacts.items()} == {
        k: without_nulls(v) for k, v in catalog.fleet_contacts.items()
    }


def test_checked_in_csvs_match_the_generator() -> None:
    """seed/seed-v1 is generated output; edit the generator or regenerate, not both."""
    checked_in = read_catalog(ROOT / "seed" / "seed-v1")
    generated = build_catalog()
    for kind in ("providers", "fleets", "units", "vehicles", "maintenance", "incidents"):
        assert without_nulls(getattr(checked_in, kind)) == without_nulls(
            getattr(generated, kind)
        ), f"seed/seed-v1 is stale: run python -m fleetops_seed generate ({kind})"


def test_every_record_passes_the_service_request_models() -> None:
    catalog = read_catalog(ROOT / "seed" / "seed-v1")
    models = [
        (catalog.providers, handlers("service-provider-master").CreateProvider),
        (catalog.fleets, handlers("fleet-master").CreateFleet),
        (catalog.units, handlers("telematics-unit-master").CreateUnit),
        (catalog.vehicles, handlers("vehicle-master").CreateVehicle),
        (catalog.maintenance, handlers("maintenance-history").RecordEvent),
        (catalog.incidents, handlers("incident-search").IndexIncident),
    ]
    for records, model in models:
        for record in records:
            model.model_validate({k: v for k, v in record.items() if v is not None})
    contacts = handlers("fleet-master").ContactsChange
    assert set(catalog.fleet_contacts) == {fleet["fleetId"] for fleet in catalog.fleets}
    for fleet_contacts in catalog.fleet_contacts.values():
        contacts.model_validate({"contacts": fleet_contacts})
