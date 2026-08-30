from typing import Any, Literal

from pydantic import Field, field_validator

from fleetops_runtime.service_support import ApiModel


Priority = Literal["low", "standard", "high", "critical"]


class EscalationContact(ApiModel):
    contact_id: str | None = Field(None, alias="contactId")
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=80)
    email: str | None = Field(None, max_length=254)
    phone: str | None = Field(None, max_length=40)
    escalation_rank: int = Field(1, alias="escalationRank", ge=1)
    active: bool = True

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        return value.strip() if value else value

    def model_post_init(self, __context: Any) -> None:
        if not self.email and not self.phone:
            raise ValueError("an escalation contact requires email or phone")


class FleetCreate(ApiModel):
    customer_name: str = Field(alias="customerName", min_length=1, max_length=160)
    industry_code: str = Field(alias="industryCode", min_length=1, max_length=64)
    declared_fleet_size: int = Field(0, alias="declaredFleetSize", ge=0)
    contract_tier: Literal[
        "basic", "standard", "premium", "enterprise"
    ] = Field(alias="contractTier")
    sla_level: Literal["standard", "enhanced", "mission_critical"] = Field(
        alias="slaLevel"
    )
    priority_level: Priority = Field("standard", alias="priorityLevel")
    preferred_service_provider_id: str | None = Field(
        None, alias="preferredServiceProviderId", max_length=64
    )
    lifecycle_status: Literal["prospect", "active", "suspended", "closed"] = (
        Field("active", alias="lifecycleStatus")
    )
    operating_regions: list[str] = Field(
        default_factory=list, alias="operatingRegions"
    )
    escalation_contacts: list[EscalationContact] = Field(
        default_factory=list, alias="escalationContacts"
    )


class FleetPatch(ApiModel):
    customer_name: str | None = Field(
        None, alias="customerName", min_length=1, max_length=160
    )
    industry_code: str | None = Field(
        None, alias="industryCode", min_length=1, max_length=64
    )
    declared_fleet_size: int | None = Field(
        None, alias="declaredFleetSize", ge=0
    )
    contract_tier: Literal[
        "basic", "standard", "premium", "enterprise"
    ] | None = Field(None, alias="contractTier")
    sla_level: Literal[
        "standard", "enhanced", "mission_critical"
    ] | None = Field(None, alias="slaLevel")
    priority_level: Priority | None = Field(None, alias="priorityLevel")
    preferred_service_provider_id: str | None = Field(
        None, alias="preferredServiceProviderId", max_length=64
    )
    lifecycle_status: Literal[
        "prospect", "active", "suspended", "closed"
    ] | None = Field(None, alias="lifecycleStatus")


class RegionsRequest(ApiModel):
    regions: list[str]


class ContactsRequest(ApiModel):
    contacts: list[EscalationContact]
