from datetime import date
from typing import Literal

from pydantic import Field

from fleetops_runtime.service_support import ApiModel


class TelematicsUnitCreate(ApiModel):
    serial_number: str = Field(alias="serialNumber", min_length=3, max_length=96)
    hardware_model: str = Field(alias="hardwareModel", min_length=1, max_length=80)
    firmware_version: str = Field(
        alias="firmwareVersion", min_length=1, max_length=64
    )
    activation_date: date | None = Field(None, alias="activationDate")
    network_carrier: str | None = Field(None, alias="networkCarrier", max_length=80)
    lifecycle_status: Literal[
        "inventory", "active", "suspended", "decommissioned"
    ] = Field("inventory", alias="lifecycleStatus")
    remote_command_eligibility: Literal[
        "eligible", "approval_required", "not_eligible"
    ] = Field("not_eligible", alias="remoteCommandEligibility")
    capabilities: list[str] = Field(default_factory=list)


class TelematicsUnitPatch(ApiModel):
    hardware_model: str | None = Field(
        None, alias="hardwareModel", min_length=1, max_length=80
    )
    activation_date: date | None = Field(None, alias="activationDate")
    network_carrier: str | None = Field(None, alias="networkCarrier", max_length=80)


class FirmwareRequest(ApiModel):
    firmware_version: str = Field(
        alias="firmwareVersion", min_length=1, max_length=64
    )


class LifecycleRequest(ApiModel):
    status: Literal["inventory", "active", "suspended", "decommissioned"]


class EligibilityRequest(ApiModel):
    eligibility: Literal["eligible", "approval_required", "not_eligible"]


class CapabilitiesRequest(ApiModel):
    capabilities: list[str]
