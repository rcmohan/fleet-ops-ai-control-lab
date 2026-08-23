from fleetops_runtime import Operation, Parameter, ServiceContract


EVENT = {"eventId": "evt_demo_001", "vehicleId": "veh_demo_001", "eventType": "battery_voltage", "severity": "warning", "regionCode": "us-east", "observedAt": "2026-08-22T12:00:00Z", "payload": {"voltage": 11.8}, "synthetic": True}

CONTRACT = ServiceContract(
    slug="telematics-event",
    title="Telematics Event Service",
    description="Synthetic telemetry ingestion, immutable event queries, and active alert projections.",
    operations=(
        Operation("POST", "/v1/events", "ingestVehicleEvent", "Ingest a synthetic vehicle event", {"eventId": "evt_demo_001", "status": "accepted", "acceptedAt": "2026-08-22T12:00:01Z"}, {"vehicleId": "veh_demo_001", "eventType": "battery_voltage", "observedAt": "2026-08-22T12:00:00Z", "payload": {"voltage": 11.8}, "synthetic": True}),
        Operation("GET", "/v1/vehicles/{vehicle_id}/events", "getRecentVehicleEvents", "Get recent vehicle events", {"items": [{**EVENT, "vehicleId": "{vehicle_id}"}], "nextCursor": ""}, parameters=(Parameter("from", required=True), Parameter("to", required=True), Parameter("cursor"), Parameter("limit", schema_type="integer"))),
        Operation("GET", "/v1/events/{event_id}", "getEventDetails", "Get event details", {**EVENT, "eventId": "{event_id}"}),
        Operation("GET", "/v1/events", "searchEventsByType", "Search events by type", {"items": [EVENT], "nextCursor": ""}, parameters=(Parameter("event_type", required=True), Parameter("from", required=True), Parameter("to", required=True), Parameter("cursor"))),
        Operation("GET", "/v1/regions/{region}/events", "searchEventsByRegion", "Search events by region", {"items": [EVENT], "nextCursor": ""}, parameters=(Parameter("from", required=True), Parameter("to", required=True), Parameter("cursor"))),
        Operation("GET", "/v1/vehicles/{vehicle_id}/active-alerts", "getActiveAlerts", "Get active vehicle alerts", {"vehicleId": "{vehicle_id}", "alerts": [{"alertId": "alert_demo_001", "eventId": "evt_demo_001", "severity": "warning", "status": "active"}]}),
    ),
)

