# Vehicle Context Facade API Signatures

```text
GetVehicleProfile(vehicleId: VehicleId, context: RequestContext)
  -> Result<VehicleProfile, ServiceError>

GetVehicleTelematicsUnit(vehicleId: VehicleId, context: RequestContext)
  -> Result<VehicleTelematicsUnitContext, ServiceError>

GetVehicleFleetAssignment(vehicleId: VehicleId, context: RequestContext)
  -> Result<VehicleFleetContext, ServiceError>

GetVehicleServiceHistory(vehicleId: VehicleId, page: PageRequest, context: RequestContext)
  -> Result<Page<MaintenanceRecord>, ServiceError>

GetVehicleCurrentState(vehicleId: VehicleId, context: RequestContext)
  -> Result<VehicleOperationalState, ServiceError>

GetVehicleContext(vehicleId: VehicleId, options: VehicleContextOptions, context: RequestContext)
  -> Result<VehicleContextBundle, ServiceError>
```

`VehicleContextBundle` identifies unavailable dependencies and the source/version of every included section. The facade does not persist authoritative joined data.

