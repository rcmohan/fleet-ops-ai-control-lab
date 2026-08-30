"""Seed one reproducible synthetic tenant exclusively through service APIs."""

from __future__ import annotations

import argparse
import json
import random
import urllib.error
import urllib.request
from typing import Any


def post(
    url: str,
    payload: dict[str, Any],
    idempotency_key: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency_key,
    }
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise RuntimeError(f"POST {url} failed ({exc.code}): {detail}") from exc


def seed(args: argparse.Namespace) -> dict[str, Any]:
    randomizer = random.Random(args.seed)
    tenant = post(
        f"{args.tenant_url}/v1/tenants",
        {
            "slug": args.tenant_slug,
            "displayName": "Northstar Synthetic Mobility",
        },
        f"seed:{args.seed}:tenant:{args.tenant_slug}",
    )
    tenant_id = tenant["tenantId"]

    provider = post(
        f"{args.provider_url}/v1/service-providers",
        {
            "providerName": "Northstar Synthetic Service Network",
            "averageResponseMinutes": 45,
            "dailyCapacity": 30,
            "regions": ["us-east", "us-central"],
            "capabilities": ["battery", "diagnostics", "tires"],
        },
        f"seed:{args.seed}:provider:primary",
        tenant_id,
    )

    units = []
    for index in range(args.vehicles):
        unit = post(
            f"{args.unit_url}/v1/telematics-units",
            {
                "serialNumber": f"TCU-{args.tenant_slug.upper()}-{index + 1:04d}",
                "hardwareModel": "NX-5G",
                "firmwareVersion": f"3.4.{index % 3}",
                "activationDate": "2026-01-15",
                "networkCarrier": "Synthetic Wireless",
                "lifecycleStatus": "active",
                "remoteCommandEligibility": "approval_required",
                "capabilities": ["diagnostics", "location", "remote_command"],
            },
            f"seed:{args.seed}:unit:{index}",
            tenant_id,
        )
        units.append(unit)

    fleets = []
    for index in range(args.fleets):
        region = "us-east" if index % 2 == 0 else "us-central"
        fleet = post(
            f"{args.fleet_url}/v1/fleets",
            {
                "customerName": f"Northstar Synthetic Fleet {index + 1}",
                "industryCode": "logistics",
                "declaredFleetSize": args.vehicles // args.fleets,
                "contractTier": "enterprise",
                "slaLevel": "mission_critical",
                "priorityLevel": "high",
                "preferredServiceProviderId": provider["providerId"],
                "operatingRegions": [region],
                "escalationContacts": [
                    {
                        "name": f"Synthetic Fleet Manager {index + 1}",
                        "role": "fleet_manager",
                        "email": f"fleet-{index + 1}@example.invalid",
                    }
                ],
            },
            f"seed:{args.seed}:fleet:{index}",
            tenant_id,
        )
        fleets.append(fleet)

    makes = [("Nova", "Transit-E"), ("Orion", "Hauler-X")]
    vehicles = []
    for index, unit in enumerate(units):
        make, model = makes[randomizer.randrange(len(makes))]
        fleet = fleets[index % len(fleets)]
        vehicle = post(
            f"{args.vehicle_url}/v1/vehicles",
            {
                "syntheticVin": f"SYNTH{args.seed:04d}{index + 1:08d}",
                "make": make,
                "model": model,
                "modelYear": 2024 + randomizer.randrange(3),
                "powertrainType": "battery_electric",
                "regionCode": fleet["operatingRegions"][0],
                "serviceStatus": "in_service",
                "warrantyStatus": "active",
                "priorityLevel": "standard",
                "fleetId": fleet["fleetId"],
                "telematicsUnitId": unit["unitId"],
            },
            f"seed:{args.seed}:vehicle:{index}",
            tenant_id,
        )
        vehicles.append(vehicle)

    return {
        "tenantId": tenant_id,
        "tenantSlug": tenant["slug"],
        "fleetCount": len(fleets),
        "vehicleCount": len(vehicles),
        "telematicsUnitCount": len(units),
        "serviceProviderCount": 1,
        "seed": args.seed,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--tenant-slug", default="northstar-demo")
    parser.add_argument("--fleets", type=int, default=2)
    parser.add_argument("--vehicles", type=int, default=20)
    parser.add_argument("--tenant-url", default="http://localhost:8100")
    parser.add_argument("--vehicle-url", default="http://localhost:8101")
    parser.add_argument("--unit-url", default="http://localhost:8102")
    parser.add_argument("--fleet-url", default="http://localhost:8103")
    parser.add_argument("--provider-url", default="http://localhost:8105")
    args = parser.parse_args()
    if args.fleets < 1 or args.vehicles < args.fleets:
        parser.error("vehicles must be greater than or equal to fleets >= 1")
    return args


if __name__ == "__main__":
    print(json.dumps(seed(parse_args()), indent=2))
