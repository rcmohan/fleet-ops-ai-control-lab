from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, Query

from fleetops_runtime.service_support import (
    MasterDataStore,
    create_service_app,
    dump_model,
    normalize_codes,
    paged,
)

from .models import ContactsRequest, FleetCreate, FleetPatch, RegionsRequest
from .seed_data import FLEETS


def _assign_contact_ids(contacts: list[dict[str, Any]]) -> None:
    for contact in contacts:
        contact["contactId"] = contact.get("contactId") or (
            f"contact_{uuid4().hex[:12]}"
        )


def create_app() -> FastAPI:
    app = create_service_app(
        slug="fleet-master",
        title="Fleet Master Service",
        description=(
            "Authoritative synthetic fleet, contract, SLA, region, "
            "and escalation metadata."
        ),
    )
    store = MasterDataStore(FLEETS)

    @app.get("/v1/fleets/{fleet_id}", operation_id="getFleetProfile")
    def get_fleet(fleet_id: str) -> dict[str, Any]:
        return store.get(fleet_id)

    @app.get("/v1/fleets/{fleet_id}/contract", operation_id="getFleetContract")
    def get_contract(fleet_id: str) -> dict[str, Any]:
        item = store.get(fleet_id)
        return {"fleetId": fleet_id, "contractTier": item["contractTier"]}

    @app.get("/v1/fleets/{fleet_id}/sla", operation_id="getFleetSla")
    def get_sla(fleet_id: str) -> dict[str, Any]:
        item = store.get(fleet_id)
        targets = {"standard": 240, "enhanced": 120, "mission_critical": 30}
        return {
            "fleetId": fleet_id,
            "slaLevel": item["slaLevel"],
            "responseTargetMinutes": targets[item["slaLevel"]],
        }

    @app.get("/v1/fleets/{fleet_id}/priority", operation_id="getFleetPriorityLevel")
    def get_priority(fleet_id: str) -> dict[str, Any]:
        item = store.get(fleet_id)
        return {"fleetId": fleet_id, "priorityLevel": item["priorityLevel"]}

    @app.get("/v1/fleets", operation_id="listFleets")
    def list_fleets(
        region: str | None = None,
        lifecycle_status: str | None = None,
        cursor: str | None = None,
        limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        items = sorted(store.list(), key=lambda item: item["fleetId"])
        if region:
            items = [item for item in items if region in item["operatingRegions"]]
        if lifecycle_status:
            items = [
                item for item in items
                if item["lifecycleStatus"] == lifecycle_status
            ]
        return paged(items, cursor, limit)

    @app.post("/v1/fleets", operation_id="createFleet")
    def create_fleet(
        body: FleetCreate,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        data = dump_model(body)
        data["operatingRegions"] = normalize_codes(
            data["operatingRegions"], "operatingRegions"
        )
        _assign_contact_ids(data["escalationContacts"])
        return store.create("flt", "fleetId", data, None, idempotency_key)

    @app.patch("/v1/fleets/{fleet_id}", operation_id="updateFleet")
    def update_fleet(
        fleet_id: str,
        body: FleetPatch,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        changes = dump_model(body, exclude_unset=True)
        return store.mutate(
            fleet_id,
            f"patch:{fleet_id}",
            idempotency_key,
            lambda record: record.update(changes),
        )

    @app.put(
        "/v1/fleets/{fleet_id}/operating-regions",
        operation_id="replaceFleetOperatingRegions",
    )
    def replace_regions(
        fleet_id: str,
        body: RegionsRequest,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        regions = normalize_codes(body.regions, "regions")
        record = store.mutate(
            fleet_id,
            f"regions:{fleet_id}",
            idempotency_key,
            lambda item: item.update(operatingRegions=regions),
        )
        return {
            "fleetId": fleet_id,
            "regions": record["operatingRegions"],
            "sourceVersion": record["sourceVersion"],
        }

    @app.put(
        "/v1/fleets/{fleet_id}/escalation-contacts",
        operation_id="replaceFleetEscalationContacts",
    )
    def replace_contacts(
        fleet_id: str,
        body: ContactsRequest,
        idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        contacts = [dump_model(contact) for contact in body.contacts]
        _assign_contact_ids(contacts)
        record = store.mutate(
            fleet_id,
            f"contacts:{fleet_id}",
            idempotency_key,
            lambda item: item.update(escalationContacts=contacts),
        )
        return {
            "fleetId": fleet_id,
            "contacts": record["escalationContacts"],
            "sourceVersion": record["sourceVersion"],
        }

    return app
