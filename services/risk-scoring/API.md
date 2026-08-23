# Risk Scoring API Signatures

```text
CalculateEventRisk(eventId: EventId, context: RequestContext)
  -> Result<RiskAssessment, ServiceError>

CalculateSlaRisk(vehicleId: VehicleId, fleetId: FleetId, context: RequestContext)
  -> Result<RiskAssessment, ServiceError>

CalculateSafetyRisk(eventId: EventId, context: RequestContext)
  -> Result<RiskAssessment, ServiceError>

CalculateCustomerImpact(eventId: EventId, context: RequestContext)
  -> Result<CustomerImpactAssessment, ServiceError>

CalculateCompositePriority(eventId: EventId, context: RequestContext)
  -> Result<PriorityAssessment, ServiceError>
```

Every assessment includes the scoring-policy version, component factors, confidence, and source references.

