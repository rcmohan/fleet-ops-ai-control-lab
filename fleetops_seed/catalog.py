"""Deterministic synthetic master data.

Every record is derived from sha256(seed_version:entity_type:entity_id), so the same seed
version and sizes always produce identical records, independent of generation order.
Timestamps are relative to a fixed anchor, never the wall clock, so re-running the loader
sends byte-identical requests. All names, brands, and values are synthetic.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

SEED_VERSION = "seed-v1"
ANCHOR = datetime(2026, 11, 1, tzinfo=UTC)

REGIONS = [
    "us-east", "us-central", "us-west", "us-south",
    "ca-east", "ca-west", "eu-west", "eu-central",
]

# (make, model, powertrain): chosen together so pairs are plausible.
MODELS = [
    ("Nova", "Transit-E", "battery_electric"),
    ("Nova", "Cargo 350", "diesel"),
    ("Kestrel", "Hauler HX", "diesel"),
    ("Kestrel", "Metro EV", "battery_electric"),
    ("Halcyon", "Route 7", "hybrid"),
    ("Halcyon", "Box 5", "gasoline"),
    ("Meridian", "Volt Van", "battery_electric"),
    ("Meridian", "Freight H2", "hydrogen"),
    ("Corvane", "City Hop", "plug_in_hybrid"),
]

HARDWARE = [("NX-5G", ["3.4.1", "3.5.0", "3.5.2"]), ("LT-4", ["2.8.0", "2.9.1"])]
CARRIERS = ["Synthetic Wireless", "Example Mobile", "Lab Telecom"]

INDUSTRIES = [
    "logistics", "utilities", "rental", "field_service", "public_transit",
    "construction", "food_distribution",
]
NAME_LEFT = [
    "Northwind", "Bluepeak", "Ironleaf", "Silverline", "Redrock", "Harbor", "Summit",
    "Cedar", "Granite", "Lakeshore", "Prairie", "Coastal", "Evergreen", "Pinecrest",
]
NAME_RIGHT = ["Logistics", "Transit", "Services", "Freight", "Distribution", "Utilities"]
PROVIDER_KINDS = ["Service Network", "Fleet Care", "Mobile Repair", "Auto Works"]
PROVIDER_CAPABILITIES = [
    "battery", "diagnostics", "tires", "brakes", "electrical", "telematics_install",
    "body_repair", "hydrogen_systems",
]

# Incident history templates per event type: symptoms, root causes, resolutions.
INCIDENT_TYPES: dict[str, dict[str, Any]] = {
    "battery_voltage": {
        "weight": 30,
        "symptoms": ["low_voltage", "missed_heartbeat", "slow_crank", "diagnostic_failure"],
        "causes": ["Battery aging", "Parasitic drain from aftermarket equipment",
                   "Alternator undercharging"],
        "resolutions": ["Battery inspected and replaced", "Charging system repaired",
                        "Aftermarket device rewired"],
        "minutes": (90, 360),
    },
    "diagnostic_failure": {
        "weight": 25,
        "symptoms": ["engine_light", "dtc_p0562", "dtc_p0300", "reduced_power"],
        "causes": ["Sensor fault", "Wiring harness damage", "Ignition misfire"],
        "resolutions": ["Sensor replaced", "Harness repaired", "Ignition components replaced"],
        "minutes": (120, 720),
    },
    "heartbeat_missed": {
        "weight": 15,
        "symptoms": ["missed_heartbeat", "stale_location", "low_voltage"],
        "causes": ["Telematics unit power loss", "Firmware watchdog reset"],
        "resolutions": ["Unit power lead reseated", "Firmware updated"],
        "minutes": (30, 240),
    },
    "connectivity_lost": {
        "weight": 15,
        "symptoms": ["no_signal", "stale_location", "missed_heartbeat"],
        "causes": ["Regional carrier outage", "Antenna damage", "SIM deactivated"],
        "resolutions": ["Recovered after carrier outage", "Antenna replaced",
                        "SIM reactivated"],
        "minutes": (20, 480),
    },
    "firmware_update_failed": {
        "weight": 10,
        "symptoms": ["update_rollback", "missed_heartbeat"],
        "causes": ["Interrupted download", "Insufficient storage on unit"],
        "resolutions": ["Update retried while parked", "Unit storage cleared and update retried"],
        "minutes": (60, 600),
    },
    "collision_detected": {
        "weight": 5,
        "symptoms": ["impact_detected", "airbag_signal", "harsh_braking"],
        "causes": ["Low-speed collision", "False positive from pothole impact"],
        "resolutions": ["Vehicle inspected and body repair scheduled",
                        "Inspection found no damage; sensor recalibrated"],
        "minutes": (240, 2880),
    },
}


def rng(seed_version: str, entity_type: str, entity_id: str) -> random.Random:
    digest = hashlib.sha256(f"{seed_version}:{entity_type}:{entity_id}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def pick_weighted(r: random.Random, options: dict[str, int]) -> str:
    return r.choices(list(options), weights=list(options.values()))[0]


def ts(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class Catalog:
    seed_version: str
    providers: list[dict[str, Any]] = field(default_factory=list)
    fleets: list[dict[str, Any]] = field(default_factory=list)
    fleet_contacts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    units: list[dict[str, Any]] = field(default_factory=list)
    vehicles: list[dict[str, Any]] = field(default_factory=list)
    maintenance: list[dict[str, Any]] = field(default_factory=list)
    incidents: list[dict[str, Any]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "providers": len(self.providers), "fleets": len(self.fleets),
            "units": len(self.units), "vehicles": len(self.vehicles),
            "maintenance": len(self.maintenance), "incidents": len(self.incidents),
        }


# Pinned records for the demo story. Generated records never use these IDs.
GOLDEN_PROVIDER = {
    "providerId": "sp_golden_east", "providerName": "Golden Battery Service East",
    "lifecycleStatus": "active", "averageResponseMinutes": 40, "dailyCapacity": 12,
    "regions": ["us-east"], "capabilities": ["battery", "diagnostics", "electrical"],
}
GOLDEN_FLEET = {
    "fleetId": "flt_golden", "customerName": "Northstar Synthetic Logistics",
    "industryCode": "logistics", "contractTier": "enterprise", "slaLevel": "mission_critical",
    "priorityLevel": "high", "preferredServiceProviderId": "sp_golden_east",
    "lifecycleStatus": "active", "contractEffectiveDate": "2026-01-01",
    "operatingRegions": ["us-east", "us-central"],
}
GOLDEN_UNIT = {
    "unitId": "tcu_golden_001", "serialNumber": "TCU-GOLDEN-0001", "hardwareModel": "NX-5G",
    "firmwareVersion": "3.5.0", "activationDate": "2026-01-15",
    "networkCarrier": "Synthetic Wireless", "lifecycleStatus": "active",
    "remoteCommandEligibility": "approval_required",
    "capabilities": ["diagnostics", "location", "remote_command"],
}
GOLDEN_VEHICLE = {
    "vehicleId": "veh_golden_001", "syntheticVin": "SYNTHGOLDEN000001", "make": "Nova",
    "model": "Transit-E", "modelYear": 2025, "powertrainType": "battery_electric",
    "regionCode": "us-east", "lifecycleStatus": "active", "serviceStatus": "in_service",
    "warrantyStatus": "active", "priorityLevel": "high", "fleetId": "flt_golden",
    "telematicsUnitId": "tcu_golden_001",
}
GOLDEN_CONTACTS = [
    {"name": "Dana Synthetic", "role": "fleet_manager", "email": "dana@example.invalid",
     "escalationRank": 1},
    {"name": "Lee Synthetic", "role": "operations_lead", "phone": "+1 555 0100",
     "escalationRank": 2},
]
GOLDEN_INCIDENTS = [
    {
        "incidentId": "inc_golden_001", "vehicleId": "veh_golden_001",
        "eventType": "battery_voltage", "symptoms": ["low_voltage", "missed_heartbeat"],
        "regionCode": "us-east", "rootCause": "Battery aging",
        "resolution": "Battery inspected and replaced", "outcome": "resolved",
        "openedAt": "2026-03-10T08:15:00Z", "resolvedAt": "2026-03-10T11:05:00Z",
    },
    {
        "incidentId": "inc_golden_002", "vehicleId": "veh_golden_001",
        "eventType": "diagnostic_failure", "symptoms": ["dtc_p0562", "low_voltage"],
        "regionCode": "us-east", "rootCause": "Alternator undercharging",
        "resolution": "Charging system repaired", "outcome": "resolved",
        "openedAt": "2026-06-02T14:00:00Z", "resolvedAt": "2026-06-02T19:30:00Z",
    },
]


def build_catalog(
    *,
    seed_version: str = SEED_VERSION,
    providers: int = 12,
    fleets: int = 20,
    vehicles: int = 500,
    spare_units: int = 20,
    incidents: int = 100,
) -> Catalog:
    catalog = Catalog(seed_version)
    sv = seed_version

    # Providers: every region gets at least one, so each fleet has a nearby provider.
    catalog.providers.append(dict(GOLDEN_PROVIDER))
    for n in range(1, providers + 1):
        pid = f"sp_{n:03d}"
        r = rng(sv, "provider", pid)
        home = REGIONS[(n - 1) % len(REGIONS)]
        extra = r.sample([x for x in REGIONS if x != home], k=r.choice([0, 1, 1, 2]))
        caps = sorted({"diagnostics", *r.sample(PROVIDER_CAPABILITIES, k=r.randint(2, 4))})
        catalog.providers.append({
            "providerId": pid,
            "providerName": f"{r.choice(NAME_LEFT)} {r.choice(PROVIDER_KINDS)} {home.upper()}",
            "lifecycleStatus": pick_weighted(r, {"active": 85, "at_capacity": 10, "suspended": 5}),
            "averageResponseMinutes": r.randrange(30, 241, 5),
            "dailyCapacity": r.randint(5, 40),
            "regions": sorted([home, *extra]),
            "capabilities": caps,
        })

    def providers_in(region: str) -> list[str]:
        return [p["providerId"] for p in catalog.providers if region in p["regions"]
                and p["lifecycleStatus"] == "active"]

    # Fleets.
    catalog.fleets.append(dict(GOLDEN_FLEET))
    catalog.fleet_contacts["flt_golden"] = [dict(c) for c in GOLDEN_CONTACTS]
    used_names = {GOLDEN_FLEET["customerName"]}
    for n in range(1, fleets + 1):
        fid = f"flt_{n:03d}"
        r = rng(sv, "fleet", fid)
        name = f"{r.choice(NAME_LEFT)} {r.choice(NAME_RIGHT)}"
        while name in used_names:
            name = f"{r.choice(NAME_LEFT)} {r.choice(NAME_RIGHT)}"
        used_names.add(name)
        regions = sorted(r.sample(REGIONS, k=r.choice([1, 1, 2, 2, 3])))
        nearby = providers_in(regions[0])
        tier = pick_weighted(r, {"basic": 20, "standard": 40, "premium": 25, "enterprise": 15})
        sla = {"basic": "standard", "standard": "standard", "premium": "enhanced",
               "enterprise": pick_weighted(r, {"enhanced": 50, "mission_critical": 50})}[tier]
        catalog.fleets.append({
            "fleetId": fid,
            "customerName": name,
            "industryCode": r.choice(INDUSTRIES),
            "contractTier": tier,
            "slaLevel": sla,
            "priorityLevel": pick_weighted(
                r, {"low": 10, "standard": 55, "high": 25, "critical": 10}
            ),
            "preferredServiceProviderId": r.choice(nearby) if nearby else None,
            "lifecycleStatus": "active",
            "contractEffectiveDate": (date(2024, 1, 1) + timedelta(days=r.randint(0, 900))).isoformat(),
            "operatingRegions": regions,
        })
        first, last = r.choice(NAME_LEFT), r.choice(["Ray", "Kim", "Lopez", "Okafor", "Novak"])
        slug = name.lower().replace(" ", "")
        catalog.fleet_contacts[fid] = [
            {"name": f"{first} {last}", "role": "fleet_manager",
             "email": f"fleet.manager@{slug}.example.invalid", "escalationRank": 1},
            {"name": f"{r.choice(NAME_LEFT)} Duty Desk", "role": "operations_lead",
             "phone": f"+1 555 {r.randint(100, 999):03d} {r.randint(1000, 9999)}",
             "escalationRank": 2},
        ]

    # Vehicles are spread over the generated fleets (the golden fleet keeps its one vehicle),
    # each in one of its fleet's regions, each with its own telematics unit.
    generated_fleets = catalog.fleets[1:]
    shares = [rng(sv, "fleet-share", f["fleetId"]).randint(1, 10) for f in generated_fleets]
    catalog.units.append(dict(GOLDEN_UNIT))
    catalog.vehicles.append(dict(GOLDEN_VEHICLE))
    fleet_sizes = {"flt_golden": 1}
    vins = {GOLDEN_VEHICLE["syntheticVin"]}
    for n in range(1, vehicles + 1):
        vid, uid = f"veh_{n:04d}", f"tcu_{n:04d}"
        r = rng(sv, "vehicle", vid)
        fleet = (r.choices(generated_fleets, weights=shares)[0] if generated_fleets
                 else catalog.fleets[0])
        make, model, powertrain = r.choice(MODELS)
        year = r.randint(2018, 2026)
        lifecycle = pick_weighted(r, {"active": 92, "inactive": 5, "ordered": 3})
        service = ("in_service" if lifecycle != "active" else
                   pick_weighted(r, {"in_service": 90, "maintenance": 7, "out_of_service": 3}))
        vin = f"SYN{r.getrandbits(56):014X}"[:17]
        while vin in vins:
            vin = f"SYN{r.getrandbits(56):014X}"[:17]
        vins.add(vin)
        catalog.vehicles.append({
            "vehicleId": vid,
            "syntheticVin": vin,
            "make": make,
            "model": model,
            "modelYear": year,
            "powertrainType": powertrain,
            "regionCode": r.choice(fleet["operatingRegions"]),
            "lifecycleStatus": lifecycle,
            "serviceStatus": service,
            "warrantyStatus": "active" if year >= 2023 else pick_weighted(
                r, {"expired": 70, "unknown": 30}),
            "priorityLevel": pick_weighted(r, {"low": 10, "standard": 75, "high": 12, "critical": 3}),
            "fleetId": fleet["fleetId"],
            "telematicsUnitId": uid,
        })
        fleet_sizes[fleet["fleetId"]] = fleet_sizes.get(fleet["fleetId"], 0) + 1

        ur = rng(sv, "unit", uid)
        hardware, firmwares = ur.choice(HARDWARE)
        unit_active = lifecycle == "active"
        catalog.units.append({
            "unitId": uid,
            "serialNumber": f"TCU-{sv.upper()}-{n:05d}",
            "hardwareModel": hardware,
            "firmwareVersion": ur.choice(firmwares),
            "activationDate": (date(year, 1, 1) + timedelta(days=ur.randint(10, 300))).isoformat()
            if unit_active else None,
            "networkCarrier": ur.choice(CARRIERS),
            "lifecycleStatus": "active" if unit_active else "inventory",
            "remoteCommandEligibility": pick_weighted(
                ur, {"eligible": 20, "approval_required": 60, "not_eligible": 20}
            ) if unit_active else "not_eligible",
            "capabilities": sorted({"diagnostics", "location",
                                    *(["remote_command"] if ur.random() < 0.6 else [])}),
        })

    for n in range(1, spare_units + 1):
        uid = f"tcu_spare_{n:03d}"
        ur = rng(sv, "unit", uid)
        hardware, firmwares = ur.choice(HARDWARE)
        catalog.units.append({
            "unitId": uid, "serialNumber": f"TCU-{sv.upper()}-SPARE-{n:03d}",
            "hardwareModel": hardware, "firmwareVersion": firmwares[-1], "activationDate": None,
            "networkCarrier": None, "lifecycleStatus": "inventory",
            "remoteCommandEligibility": "not_eligible", "capabilities": ["diagnostics", "location"],
        })

    for fleet in catalog.fleets:
        fleet["declaredFleetSize"] = fleet_sizes.get(fleet["fleetId"], 0)

    # Maintenance history: 0-3 past visits per vehicle, odometer rising over time.
    for vehicle in catalog.vehicles:
        vid = vehicle["vehicleId"]
        r = rng(sv, "maintenance", vid)
        if vehicle["lifecycleStatus"] == "ordered":
            continue
        visits = 2 if vid == "veh_golden_001" else r.choice([0, 1, 1, 2, 2, 3])
        odometer = r.uniform(2000, 15000)
        opened = ANCHOR - timedelta(days=r.randint(400, 540))
        nearby = providers_in(vehicle["regionCode"])
        for visit in range(1, visits + 1):
            opened += timedelta(days=r.randint(60, 150), hours=r.randint(7, 16))
            odometer += r.uniform(4000, 20000)
            event_type = pick_weighted(
                r, {"preventive": 45, "inspection": 25, "repair": 20, "diagnostic": 7, "recall": 3}
            )
            hours = r.randint(1, 8)
            catalog.maintenance.append({
                "maintenanceId": f"mtn_{vid.removeprefix('veh_')}_{visit}",
                "vehicleId": vid,
                "serviceProviderId": r.choice(nearby) if nearby else None,
                "eventType": event_type,
                "serviceStatus": "completed",
                "openedAt": ts(opened),
                "completedAt": ts(opened + timedelta(hours=hours)),
                "odometerKm": round(odometer, 1),
                "summary": {
                    "preventive": "Scheduled preventive service",
                    "inspection": "Periodic safety inspection",
                    "repair": r.choice(["Brake pads replaced", "Coolant leak repaired",
                                        "Suspension bushing replaced"]),
                    "diagnostic": "Diagnostic check after warning light",
                    "recall": "Synthetic recall campaign completed",
                }[event_type],
                "resolution": "Completed without findings" if event_type in {
                    "preventive", "inspection"} else "Repair completed",
                "sourceReference": f"{sv}/maintenance",
            })

    # Resolved incident history for similarity search and statistics.
    catalog.incidents.extend(dict(i) for i in GOLDEN_INCIDENTS)
    eligible = [v for v in catalog.vehicles if v["lifecycleStatus"] != "ordered"
                and v["vehicleId"] != "veh_golden_001"]
    weights = {name: spec["weight"] for name, spec in INCIDENT_TYPES.items()}
    for n in range(1, incidents + 1):
        iid = f"inc_hist_{n:04d}"
        r = rng(sv, "incident", iid)
        event_type = pick_weighted(r, weights)
        spec = INCIDENT_TYPES[event_type]
        vehicle = r.choice(eligible)
        opened = ANCHOR - timedelta(days=r.randint(15, 365), minutes=r.randint(0, 1439))
        low, high = spec["minutes"]
        index = r.randrange(len(spec["causes"]))
        outcome = pick_weighted(r, {"resolved": 85, "workaround": 10, "unresolved": 5})
        catalog.incidents.append({
            "incidentId": iid,
            "vehicleId": vehicle["vehicleId"],
            "eventType": event_type,
            "symptoms": sorted(r.sample(spec["symptoms"], k=r.randint(1, min(3, len(spec["symptoms"]))))),
            "regionCode": vehicle["regionCode"],
            "rootCause": spec["causes"][index],
            "resolution": spec["resolutions"][min(index, len(spec["resolutions"]) - 1)],
            "outcome": outcome,
            "openedAt": ts(opened),
            "resolvedAt": ts(opened + timedelta(minutes=int(r.triangular(low, high, low * 1.5)))),
        })

    return catalog
