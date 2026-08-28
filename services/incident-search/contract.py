from fleetops_runtime import Operation, Parameter, ServiceContract


CONTRACT = ServiceContract(
    slug="incident-search",
    title="Prior Incident Search Service",
    description="Retrieval and aggregate analysis over synthetic resolved incident history.",
    operations=(
        Operation(
            method="POST",
            path="/v1/incidents/search",
            operation_id="searchSimilarIncidents",
            summary="Search similar incidents",
            response={
                "items": [
                    {
                        "incidentId": "inc_demo_001",
                        "similarity": 0.88,
                        "eventType": "battery_voltage",
                        "outcome": "resolved",
                    }
                ],
                "nextCursor": "",
            },
            request={
                "eventType": "battery_voltage",
                "symptoms": ["low_voltage"],
                "regionCode": "us-east",
            },
            parameters=(Parameter("cursor"), Parameter("limit", schema_type="integer")),
        ),
        Operation(
            method="GET",
            path="/v1/incidents/{incident_id}/resolution",
            operation_id="getIncidentResolution",
            summary="Get incident resolution",
            response={
                "incidentId": "{incident_id}",
                "rootCause": "Synthetic battery aging",
                "resolution": "Battery inspected and replaced",
                "outcome": "resolved",
                "timeToResolveMinutes": 180,
            },
        ),
        Operation(
            method="GET",
            path="/v1/incident-patterns/resolutions",
            operation_id="getCommonResolutionPatterns",
            summary="Get common resolution patterns",
            response={
                "eventType": "battery_voltage",
                "patterns": [
                    {
                        "resolution": "Inspect battery",
                        "occurrences": 12,
                        "successRate": 0.92,
                    }
                ],
            },
            parameters=(Parameter("event_type", required=True),),
        ),
        Operation(
            method="GET",
            path="/v1/incident-statistics/resolution-time",
            operation_id="getHistoricalResolutionTime",
            summary="Get historical resolution-time statistics",
            response={
                "eventType": "battery_voltage",
                "sampleSize": 20,
                "medianMinutes": 150,
                "p95Minutes": 360,
            },
            parameters=(Parameter("event_type", required=True),),
        ),
    ),
)
