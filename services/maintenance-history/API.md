# Maintenance History API Signatures

```text
GetMaintenanceRecord(maintenanceId: MaintenanceId, context: RequestContext)
  -> Result<MaintenanceRecord, ServiceError>

GetVehicleServiceHistory(vehicleId: VehicleId, page: PageRequest, context: RequestContext)
  -> Result<Page<MaintenanceRecord>, ServiceError>

RecordMaintenanceEvent(command: RecordMaintenanceEvent, context: RequestContext)
  -> Result<MaintenanceRecord, ServiceError>

CorrectMaintenanceRecord(maintenanceId: MaintenanceId, correction: MaintenanceCorrection, context: RequestContext)
  -> Result<MaintenanceRecord, ServiceError>
```

`VehicleId` and `ServiceProviderId` are opaque external references. Corrections preserve audit history rather than silently replacing source facts.

