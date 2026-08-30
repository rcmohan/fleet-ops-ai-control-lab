from typing import Literal

from pydantic import Field

from fleetops_runtime.service_support import ApiModel


class ProviderCreate(ApiModel):
    provider_name: str = Field(alias="providerName", min_length=1, max_length=160)
    lifecycle_status: Literal[
        "active", "at_capacity", "suspended", "closed"
    ] = Field("active", alias="lifecycleStatus")
    average_response_minutes: int | None = Field(
        None, alias="averageResponseMinutes", ge=0
    )
    daily_capacity: int | None = Field(None, alias="dailyCapacity", ge=0)
    regions: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


class ProviderPatch(ApiModel):
    provider_name: str | None = Field(
        None, alias="providerName", min_length=1, max_length=160
    )
    average_response_minutes: int | None = Field(
        None, alias="averageResponseMinutes", ge=0
    )
    daily_capacity: int | None = Field(None, alias="dailyCapacity", ge=0)


class LifecycleRequest(ApiModel):
    status: Literal["active", "at_capacity", "suspended", "closed"]


class CoverageRequest(ApiModel):
    regions: list[str]
    capabilities: list[str]
