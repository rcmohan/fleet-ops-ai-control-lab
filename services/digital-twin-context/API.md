# Digital Twin Context API Signatures

```text
GetVehicleOperationalState(vehicleId: VehicleId, context: RequestContext)
  -> Result<VehicleOperationalState, ServiceError>

GetFleetOperationalState(fleetId: FleetId, context: RequestContext)
  -> Result<FleetOperationalState, ServiceError>

GetRelatedEntities(entityId: EntityId, context: RequestContext)
  -> Result<RelatedEntity[], ServiceError>

GetDownstreamImpact(eventId: EventId, context: RequestContext)
  -> Result<DownstreamImpact, ServiceError>

GetDependencyGraph(entityId: EntityId, context: RequestContext)
  -> Result<DependencyGraph, ServiceError>

ApplyOperationalEvent(event: VehicleEvent, context: RequestContext)
  -> Result<StateUpdateReceipt, ServiceError>
```

