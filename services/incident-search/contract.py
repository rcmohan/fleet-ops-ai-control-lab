from fleetops_runtime import Operation, Parameter, ServiceContract


CONTRACT = ServiceContract(
    slug="incident-search",
    title="Prior Incident Search Service",
    description="Retrieval and aggregate analysis over synthetic resolved incident history.",
    operations=(
        Operation("POST", "/v1/incidents/search", "searchSimilarIncidents", "Search similar incidents", {"items": [{"incidentId": "inc_demo_001", "similarity": 0.88, "eventType": "battery_voltage", "outcome": "resolved"}], "nextCursor": ""}, {"eventType": "battery_voltage", "symptoms": ["low_voltage"], "regionCode": "us-east"}, parameters=(Parameter("cursor"), Parameter("limit", schema_type="integer"))),
        Operation("GET", "/v1/incidents/{incident_id}/resolution", "getIncidentResolution", "Get incident resolution", {"incidentId": "{incident_id}", "rootCause": "Synthetic battery aging", "resolution": "Battery inspected and replaced", "outcome": "resolved", "timeToResolveMinutes": 180}),
        Operation("GET", "/v1/incident-patterns/resolutions", "getCommonResolutionPatterns", "Get common resolution patterns", {"eventType": "battery_voltage", "patterns": [{"resolution": "Inspect battery", "occurrences": 12, "successRate": 0.92}]}, parameters=(Parameter("event_type", required=True),)),
        Operation("GET", "/v1/incident-statistics/resolution-time", "getHistoricalResolutionTime", "Get historical resolution-time statistics", {"eventType": "battery_voltage", "sampleSize": 20, "medianMinutes": 150, "p95Minutes": 360}, parameters=(Parameter("event_type", required=True),)),
    ),
)

