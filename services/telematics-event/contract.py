from fleetops_runtime import Operation, Parameter, ServiceContract


EVENT = {
    "eventId": "evt_demo_001",
    "vehicleId": "veh_demo_001",
    "eventType": "battery_voltage",
    "severity": "warning",
    "regionCode": "us-east",
    "observedAt": "2026-08-22T12:00:00Z",
    "payload": {"voltage": 11.8},
    "synthetic": True,
}

CONTRACT = ServiceContract(
    slug="telematics-event",
    title="Telematics Event Service",
    description="Synthetic telemetry ingestion, immutable event queries, and active alert projections.",
    operations=(
        Operation(
            method="POST",
            path="/v1/events",
            operation_id="ingestVehicleEvent",
            summary="Ingest a synthetic vehicle event",
            response={
                "eventId": "evt_demo_001",
                "status": "accepted",
                "acceptedAt": "2026-08-22T12:00:01Z",
            },
            request={
                "vehicleId": "veh_demo_001",
                "eventType": "battery_voltage",
                "observedAt": "2026-08-22T12:00:00Z",
                "payload": {"voltage": 11.8},
                "synthetic": True,
            },
        ),
        Operation(
            method="GET",
            path="/v1/vehicles/{vehicle_id}/events",
            operation_id="getRecentVehicleEvents",
            summary="Get recent vehicle events",
            response={
                "items": [{**EVENT, "vehicleId": "{vehicle_id}"}],
                "nextCursor": "",
            },
            parameters=(
                Parameter("from", required=True),
                Parameter("to", required=True),
                Parameter("cursor"),
                Parameter("limit", schema_type="integer"),
            ),
        ),
        Operation(
            method="GET",
            path="/v1/events/{event_id}",
            operation_id="getEventDetails",
            summary="Get event details",
            response={**EVENT, "eventId": "{event_id}"},
        ),
        Operation(
            method="GET",
            path="/v1/events",
            operation_id="searchEventsByType",
            summary="Search events by type",
            response={"items": [EVENT], "nextCursor": ""},
            parameters=(
                Parameter("event_type", required=True),
                Parameter("from", required=True),
                Parameter("to", required=True),
                Parameter("cursor"),
            ),
        ),
        Operation(
            method="GET",
            path="/v1/regions/{region}/events",
            operation_id="searchEventsByRegion",
            summary="Search events by region",
            response={"items": [EVENT], "nextCursor": ""},
            parameters=(
                Parameter("from", required=True),
                Parameter("to", required=True),
                Parameter("cursor"),
            ),
        ),
        Operation(
            method="GET",
            path="/v1/vehicles/{vehicle_id}/active-alerts",
            operation_id="getActiveAlerts",
            summary="Get active vehicle alerts",
            response={
                "vehicleId": "{vehicle_id}",
                "alerts": [
                    {
                        "alertId": "alert_demo_001",
                        "eventId": "evt_demo_001",
                        "severity": "warning",
                        "status": "active",
                    }
                ],
            },
        ),
    ),
)
