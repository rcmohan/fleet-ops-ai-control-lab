from typing import Literal

from pydantic import Field, field_validator

from fleetops_runtime.service_support import ApiModel


class TenantCreate(ApiModel):
    slug: str = Field(min_length=3, max_length=48, pattern=r"^[a-z0-9-]+$")
    display_name: str = Field(alias="displayName", min_length=1, max_length=160)
    lifecycle_status: Literal["active", "suspended", "closed"] = Field(
        "active", alias="lifecycleStatus"
    )

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return value.lower()


class TenantPatch(ApiModel):
    display_name: str | None = Field(
        None, alias="displayName", min_length=1, max_length=160
    )
    lifecycle_status: Literal["active", "suspended", "closed"] | None = Field(
        None, alias="lifecycleStatus"
    )
