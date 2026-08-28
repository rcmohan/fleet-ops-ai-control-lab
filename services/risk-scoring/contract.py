from fleetops_runtime import Operation, ServiceContract


RISK = {
    "score": 42.0,
    "level": "medium",
    "confidence": 0.84,
    "factors": [{"name": "severity", "contribution": 20.0}],
    "scoringPolicyVersion": "1.0",
}

CONTRACT = ServiceContract(
    slug="risk-scoring",
    title="Risk Scoring Service",
    description="Explainable synthetic event, safety, SLA, customer-impact, and priority scoring.",
    operations=(
        Operation(
            method="GET",
            path="/v1/risk/events/{event_id}",
            operation_id="calculateEventRisk",
            summary="Calculate event risk",
            response={"eventId": "{event_id}", **RISK},
        ),
        Operation(
            method="GET",
            path="/v1/risk/vehicles/{vehicle_id}/fleets/{fleet_id}/sla",
            operation_id="calculateSlaRisk",
            summary="Calculate SLA risk",
            response={"vehicleId": "{vehicle_id}", "fleetId": "{fleet_id}", **RISK},
        ),
        Operation(
            method="GET",
            path="/v1/risk/events/{event_id}/safety",
            operation_id="calculateSafetyRisk",
            summary="Calculate safety risk",
            response={"eventId": "{event_id}", **RISK},
        ),
        Operation(
            method="GET",
            path="/v1/risk/events/{event_id}/customer-impact",
            operation_id="calculateCustomerImpact",
            summary="Calculate customer impact",
            response={
                "eventId": "{event_id}",
                "affectedFleetIds": ["flt_demo_001"],
                "affectedVehicleCount": 1,
                **RISK,
            },
        ),
        Operation(
            method="GET",
            path="/v1/risk/events/{event_id}/composite-priority",
            operation_id="calculateCompositePriority",
            summary="Calculate composite priority",
            response={
                "eventId": "{event_id}",
                "priorityScore": 54.0,
                "urgency": "medium",
                "confidence": 0.84,
                "componentScores": {"event": 42.0, "safety": 20.0, "sla": 65.0},
                "scoringPolicyVersion": "1.0",
            },
        ),
    ),
)
