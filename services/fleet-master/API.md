# Fleet Master API Signatures

```text
GetFleetProfile(fleetId: FleetId, context: RequestContext)
  -> Result<FleetProfile, ServiceError>

GetFleetContract(fleetId: FleetId, context: RequestContext)
  -> Result<FleetContract, ServiceError>

GetFleetSla(fleetId: FleetId, context: RequestContext)
  -> Result<FleetSla, ServiceError>

GetFleetPriorityLevel(fleetId: FleetId, context: RequestContext)
  -> Result<FleetPriority, ServiceError>

CreateFleet(command: CreateFleet, context: RequestContext)
  -> Result<FleetProfile, ServiceError>

UpdateFleet(fleetId: FleetId, changes: FleetChanges, context: RequestContext)
  -> Result<FleetProfile, ServiceError>

ReplaceFleetOperatingRegions(fleetId: FleetId, regions: RegionCode[], context: RequestContext)
  -> Result<FleetOperatingRegions, ServiceError>

ReplaceFleetEscalationContacts(fleetId: FleetId, contacts: EscalationContactInput[], context: RequestContext)
  -> Result<FleetEscalationContacts, ServiceError>
```

Vehicle membership is queried from Vehicle Master by `fleetId`; it is not owned by Fleet Master.

