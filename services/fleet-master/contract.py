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
        Operation("GET", "/v1/fleets/{fleet_id}", "getFleetProfile", "Get a fleet profile", {**FLEET, "fleetId": "{fleet_id}"}),
        Operation("GET", "/v1/fleets/{fleet_id}/contract", "getFleetContract", "Get fleet contract classification", {"fleetId": "{fleet_id}", "contractTier": "enterprise", "effectiveDate": "2026-01-01"}),
        Operation("GET", "/v1/fleets/{fleet_id}/sla", "getFleetSla", "Get fleet SLA classification", {"fleetId": "{fleet_id}", "slaLevel": "mission_critical", "responseTargetMinutes": 30}),
        Operation("GET", "/v1/fleets/{fleet_id}/priority", "getFleetPriorityLevel", "Get fleet priority", {"fleetId": "{fleet_id}", "priorityLevel": "high"}),
        Operation("GET", "/v1/fleets", "listFleets", "List fleets", {"items": [FLEET], "nextCursor": ""}, parameters=(Parameter("region"), Parameter("lifecycle_status"), Parameter("cursor"), Parameter("limit", schema_type="integer"))),
        Operation("POST", "/v1/fleets", "createFleet", "Create a synthetic fleet", FLEET, {"customerName": "Northstar Synthetic Logistics", "industryCode": "logistics", "contractTier": "enterprise", "slaLevel": "mission_critical"}),
        Operation("PATCH", "/v1/fleets/{fleet_id}", "updateFleet", "Update fleet-owned fields", {**FLEET, "fleetId": "{fleet_id}", "sourceVersion": 2}, {"priorityLevel": "critical"}),
        Operation("PUT", "/v1/fleets/{fleet_id}/operating-regions", "replaceFleetOperatingRegions", "Replace fleet operating regions", {"fleetId": "{fleet_id}", "regions": ["us-east", "us-central"], "sourceVersion": 2}, {"regions": ["us-east", "us-central"]}),
        Operation("PUT", "/v1/fleets/{fleet_id}/escalation-contacts", "replaceFleetEscalationContacts", "Replace fleet escalation contacts", {"fleetId": "{fleet_id}", "contacts": [{"contactId": "contact_demo_001", "name": "Demo Reviewer", "role": "fleet_manager"}], "sourceVersion": 2}, {"contacts": [{"name": "Demo Reviewer", "role": "fleet_manager", "email": "reviewer@example.invalid"}]}),
    ),
)
