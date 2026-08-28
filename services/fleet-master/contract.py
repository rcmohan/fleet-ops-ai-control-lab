from fleetops_runtime import Operation, Parameter, ServiceContract


FLEET = {
    "fleetId": "flt_demo_001",
    "customerName": "Northstar Synthetic Logistics",
    "industryCode": "logistics",
    "declaredFleetSize": 100,
    "contractTier": "enterprise",
    "slaLevel": "mission_critical",
    "priorityLevel": "high",
    "preferredServiceProviderId": "sp_demo_001",
    "lifecycleStatus": "active",
    "operatingRegions": ["us-east", "us-central"],
    "sourceVersion": 1,
}

CONTRACT = ServiceContract(
    slug="fleet-master",
    title="Fleet Master Service",
    description="Authoritative synthetic fleet, contract, SLA, region, and escalation metadata.",
    operations=(
        Operation(
            method="GET",
            path="/v1/fleets/{fleet_id}",
            operation_id="getFleetProfile",
            summary="Get a fleet profile",
            response={**FLEET, "fleetId": "{fleet_id}"},
        ),
        Operation(
            method="GET",
            path="/v1/fleets/{fleet_id}/contract",
            operation_id="getFleetContract",
            summary="Get fleet contract classification",
            response={
                "fleetId": "{fleet_id}",
                "contractTier": "enterprise",
                "effectiveDate": "2026-01-01",
            },
        ),
        Operation(
            method="GET",
            path="/v1/fleets/{fleet_id}/sla",
            operation_id="getFleetSla",
            summary="Get fleet SLA classification",
            response={
                "fleetId": "{fleet_id}",
                "slaLevel": "mission_critical",
                "responseTargetMinutes": 30,
            },
        ),
        Operation(
            method="GET",
            path="/v1/fleets/{fleet_id}/priority",
            operation_id="getFleetPriorityLevel",
            summary="Get fleet priority",
            response={"fleetId": "{fleet_id}", "priorityLevel": "high"},
        ),
        Operation(
            method="GET",
            path="/v1/fleets",
            operation_id="listFleets",
            summary="List fleets",
            response={"items": [FLEET], "nextCursor": ""},
            parameters=(
                Parameter("region"),
                Parameter("lifecycle_status"),
                Parameter("cursor"),
                Parameter("limit", schema_type="integer"),
            ),
        ),
        Operation(
            method="POST",
            path="/v1/fleets",
            operation_id="createFleet",
            summary="Create a synthetic fleet",
            response=FLEET,
            request={
                "customerName": "Northstar Synthetic Logistics",
                "industryCode": "logistics",
                "contractTier": "enterprise",
                "slaLevel": "mission_critical",
            },
        ),
        Operation(
            method="PATCH",
            path="/v1/fleets/{fleet_id}",
            operation_id="updateFleet",
            summary="Update fleet-owned fields",
            response={**FLEET, "fleetId": "{fleet_id}", "sourceVersion": 2},
            request={"priorityLevel": "critical"},
        ),
        Operation(
            method="PUT",
            path="/v1/fleets/{fleet_id}/operating-regions",
            operation_id="replaceFleetOperatingRegions",
            summary="Replace fleet operating regions",
            response={
                "fleetId": "{fleet_id}",
                "regions": ["us-east", "us-central"],
                "sourceVersion": 2,
            },
            request={"regions": ["us-east", "us-central"]},
        ),
        Operation(
            method="PUT",
            path="/v1/fleets/{fleet_id}/escalation-contacts",
            operation_id="replaceFleetEscalationContacts",
            summary="Replace fleet escalation contacts",
            response={
                "fleetId": "{fleet_id}",
                "contacts": [
                    {
                        "contactId": "contact_demo_001",
                        "name": "Demo Reviewer",
                        "role": "fleet_manager",
                    }
                ],
                "sourceVersion": 2,
            },
            request={
                "contacts": [
                    {
                        "name": "Demo Reviewer",
                        "role": "fleet_manager",
                        "email": "reviewer@example.invalid",
                    }
                ]
            },
        ),
    ),
)
