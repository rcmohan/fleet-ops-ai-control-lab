# Telematics Event API Signatures

```text
IngestVehicleEvent(event: VehicleEventInput, context: RequestContext)
  -> Result<AcceptedVehicleEvent, ServiceError>

GetRecentVehicleEvents(vehicleId: VehicleId, window: TimeWindow, page: PageRequest, context: RequestContext)
  -> Result<Page<VehicleEvent>, ServiceError>

GetEventDetails(eventId: EventId, context: RequestContext)
  -> Result<VehicleEvent, ServiceError>

SearchEventsByType(eventType: EventType, window: TimeWindow, page: PageRequest, context: RequestContext)
  -> Result<Page<VehicleEvent>, ServiceError>

SearchEventsByRegion(region: RegionCode, window: TimeWindow, page: PageRequest, context: RequestContext)
  -> Result<Page<VehicleEvent>, ServiceError>

GetActiveAlerts(vehicleId: VehicleId, context: RequestContext)
  -> Result<ActiveAlert[], ServiceError>
```

