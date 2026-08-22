# Vehicle Master API Signatures

```text
GetVehicleProfile(vehicleId: VehicleId, context: RequestContext)
  -> Result<VehicleProfile, ServiceError>

CreateVehicle(command: CreateVehicle, context: RequestContext)
  -> Result<VehicleProfile, ServiceError>

UpdateVehicleProfile(vehicleId: VehicleId, changes: VehicleProfileChanges, context: RequestContext)
  -> Result<VehicleProfile, ServiceError>

SetVehicleLifecycleStatus(vehicleId: VehicleId, status: VehicleLifecycleStatus, context: RequestContext)
  -> Result<VehicleProfile, ServiceError>

AssignVehicleToFleet(vehicleId: VehicleId, fleetId: FleetId?, context: RequestContext)
  -> Result<VehicleAssignmentReferences, ServiceError>

AssignTelematicsUnit(vehicleId: VehicleId, unitId: TelematicsUnitId?, context: RequestContext)
  -> Result<VehicleAssignmentReferences, ServiceError>

ListVehiclesByFleet(fleetId: FleetId, page: PageRequest, context: RequestContext)
  -> Result<Page<VehicleSummary>, ServiceError>
```

`FleetId` and `TelematicsUnitId` are opaque external references. `VehicleProfile` contains only vehicle-owned attributes and reference IDs.

