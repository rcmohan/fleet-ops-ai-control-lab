from fleetops_runtime import Operation, ServiceContract


RISK = {"score": 42.0, "level": "medium", "confidence": 0.84, "factors": [{"name": "severity", "contribution": 20.0}], "scoringPolicyVersion": "1.0"}

CONTRACT = ServiceContract(
    slug="risk-scoring",
    title="Risk Scoring Service",
    description="Explainable synthetic event, safety, SLA, customer-impact, and priority scoring.",
    operations=(
        Operation("GET", "/v1/risk/events/{event_id}", "calculateEventRisk", "Calculate event risk", {"eventId": "{event_id}", **RISK}),
        Operation("GET", "/v1/risk/vehicles/{vehicle_id}/fleets/{fleet_id}/sla", "calculateSlaRisk", "Calculate SLA risk", {"vehicleId": "{vehicle_id}", "fleetId": "{fleet_id}", **RISK}),
        Operation("GET", "/v1/risk/events/{event_id}/safety", "calculateSafetyRisk", "Calculate safety risk", {"eventId": "{event_id}", **RISK}),
        Operation("GET", "/v1/risk/events/{event_id}/customer-impact", "calculateCustomerImpact", "Calculate customer impact", {"eventId": "{event_id}", "affectedFleetIds": ["flt_demo_001"], "affectedVehicleCount": 1, **RISK}),
        Operation("GET", "/v1/risk/events/{event_id}/composite-priority", "calculateCompositePriority", "Calculate composite priority", {"eventId": "{event_id}", "priorityScore": 54.0, "urgency": "medium", "confidence": 0.84, "componentScores": {"event": 42.0, "safety": 20.0, "sla": 65.0}, "scoringPolicyVersion": "1.0"}),
    ),
)

