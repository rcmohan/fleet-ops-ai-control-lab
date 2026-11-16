"""CSV files for a catalog: one file per entity, the columns are the API field names.

List columns hold values separated by ';'. An empty cell is null (an empty list for list
columns). Fleet escalation contacts are one row per contact, keyed by fleetId.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .catalog import Catalog

LIST, INT, FLOAT, STR = "list", "int", "float", "str"

# file name -> (Catalog attribute, [(column, type)])
FILES: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "service_providers.csv": ("providers", [
        ("providerId", STR), ("providerName", STR), ("lifecycleStatus", STR),
        ("averageResponseMinutes", INT), ("dailyCapacity", INT),
        ("regions", LIST), ("capabilities", LIST),
    ]),
    "fleets.csv": ("fleets", [
        ("fleetId", STR), ("customerName", STR), ("industryCode", STR),
        ("contractTier", STR), ("slaLevel", STR), ("priorityLevel", STR),
        ("preferredServiceProviderId", STR), ("lifecycleStatus", STR),
        ("contractEffectiveDate", STR), ("operatingRegions", LIST), ("declaredFleetSize", INT),
    ]),
    "telematics_units.csv": ("units", [
        ("unitId", STR), ("serialNumber", STR), ("hardwareModel", STR),
        ("firmwareVersion", STR), ("activationDate", STR), ("networkCarrier", STR),
        ("lifecycleStatus", STR), ("remoteCommandEligibility", STR), ("capabilities", LIST),
    ]),
    "vehicles.csv": ("vehicles", [
        ("vehicleId", STR), ("syntheticVin", STR), ("make", STR), ("model", STR),
        ("modelYear", INT), ("powertrainType", STR), ("regionCode", STR),
        ("lifecycleStatus", STR), ("serviceStatus", STR), ("warrantyStatus", STR),
        ("priorityLevel", STR), ("fleetId", STR), ("telematicsUnitId", STR),
    ]),
    "maintenance_records.csv": ("maintenance", [
        ("maintenanceId", STR), ("vehicleId", STR), ("serviceProviderId", STR),
        ("eventType", STR), ("serviceStatus", STR), ("openedAt", STR), ("completedAt", STR),
        ("odometerKm", FLOAT), ("summary", STR), ("resolution", STR), ("sourceReference", STR),
    ]),
    "incidents.csv": ("incidents", [
        ("incidentId", STR), ("vehicleId", STR), ("eventType", STR), ("symptoms", LIST),
        ("regionCode", STR), ("rootCause", STR), ("resolution", STR), ("outcome", STR),
        ("openedAt", STR), ("resolvedAt", STR),
    ]),
}
CONTACTS_FILE = "fleet_contacts.csv"
CONTACT_COLUMNS = [("fleetId", STR), ("name", STR), ("role", STR), ("email", STR),
                   ("phone", STR), ("escalationRank", INT)]
VERSION_FILE = "SEED_VERSION"


def _write_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        if any(";" in str(item) for item in value):
            raise ValueError(f"list item contains ';': {value}")
        return ";".join(str(item) for item in value)
    return str(value)


def _read_cell(raw: str, kind: str, where: str) -> Any:
    raw = raw.strip()
    if kind == LIST:
        return [item.strip() for item in raw.split(";") if item.strip()]
    if raw == "":
        return None
    try:
        if kind == INT:
            return int(raw)
        if kind == FLOAT:
            return float(raw)
    except ValueError as exc:
        raise ValueError(f"{where}: {raw!r} is not a valid {kind}") from exc
    return raw


def _write(path: Path, columns: list[tuple[str, str]], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([name for name, _ in columns])
        for row in rows:
            writer.writerow([_write_cell(row.get(name)) for name, _ in columns])


def _read(path: Path, columns: list[tuple[str, str]]) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        expected = [name for name, _ in columns]
        missing = [name for name in expected if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name}: missing columns {missing}")
        return [
            {name: _read_cell(row[name] or "", kind, f"{path.name} line {line}, {name}")
             for name, kind in columns}
            for line, row in enumerate(reader, start=2)
        ]


def write_catalog(catalog: Catalog, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for file_name, (attribute, columns) in FILES.items():
        _write(directory / file_name, columns, getattr(catalog, attribute))
        written.append(directory / file_name)
    contacts = [{"fleetId": fleet_id, **contact}
                for fleet_id, items in catalog.fleet_contacts.items() for contact in items]
    _write(directory / CONTACTS_FILE, CONTACT_COLUMNS, contacts)
    (directory / VERSION_FILE).write_text(catalog.seed_version + "\n", encoding="utf-8")
    return [*written, directory / CONTACTS_FILE]


def read_catalog(directory: Path) -> Catalog:
    version_file = directory / VERSION_FILE
    version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "csv"
    catalog = Catalog(version)
    for file_name, (attribute, columns) in FILES.items():
        setattr(catalog, attribute, _read(directory / file_name, columns))
    contacts_path = directory / CONTACTS_FILE
    if contacts_path.exists():
        for row in _read(contacts_path, CONTACT_COLUMNS):
            fleet_id = row.pop("fleetId")
            catalog.fleet_contacts.setdefault(fleet_id, []).append(row)
    return catalog
