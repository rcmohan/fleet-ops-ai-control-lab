from typing import Literal

from pydantic import Field, field_validator

from fleetops_runtime.service_support import ApiModel


Powertrain = Literal[
    "gasoline", "diesel", "hybrid", "plug_in_hybrid",
    "battery_electric", "hydrogen", "other",
]
Priority = Literal["low", "standard", "high", "critical"]


class VehicleCreate(ApiModel):
    synthetic_vin: str = Field(alias="syntheticVin", min_length=8, max_length=32)
    make: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=80)
    model_year: int = Field(alias="modelYear", ge=1980, le=2200)
    powertrain_type: Powertrain = Field(alias="powertrainType")
    region_code: str = Field(alias="regionCode", min_length=1, max_length=32)
    service_status: Literal[
        "in_service", "maintenance", "out_of_service", "retired"
    ] = Field("in_service", alias="serviceStatus")
    warranty_status: Literal["active", "expired", "unknown"] = Field(
        "unknown", alias="warrantyStatus"
    )
    priority_level: Priority = Field("standard", alias="priorityLevel")
    fleet_id: str | None = Field(None, alias="fleetId", max_length=64)
    telematics_unit_id: str | None = Field(
        None, alias="telematicsUnitId", max_length=64
    )

    @field_validator("synthetic_vin")
    @classmethod
    def require_synthetic_vin(cls, value: str) -> str:
        if not value.upper().startswith("SYNTH"):
            raise ValueError("syntheticVin must start with 'SYNTH'")
        return value.upper()


class VehiclePatch(ApiModel):
    make: str | None = Field(None, min_length=1, max_length=80)
    model: str | None = Field(None, min_length=1, max_length=80)
    model_year: int | None = Field(None, alias="modelYear", ge=1980, le=2200)
    powertrain_type: Powertrain | None = Field(None, alias="powertrainType")
    region_code: str | None = Field(
        None, alias="regionCode", min_length=1, max_length=32
    )
    service_status: Literal[
        "in_service", "maintenance", "out_of_service", "retired"
    ] | None = Field(None, alias="serviceStatus")
    warranty_status: Literal["active", "expired", "unknown"] | None = Field(
        None, alias="warrantyStatus"
    )
    priority_level: Priority | None = Field(None, alias="priorityLevel")


class LifecycleRequest(ApiModel):
    status: Literal["ordered", "active", "inactive", "retired"]


class FleetAssignment(ApiModel):
    fleet_id: str | None = Field(None, alias="fleetId", max_length=64)


class UnitAssignment(ApiModel):
    telematics_unit_id: str | None = Field(
        None, alias="telematicsUnitId", max_length=64
    )
