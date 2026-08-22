# Telematics Unit Master API Signatures

```text
GetTelematicsUnit(unitId: TelematicsUnitId, context: RequestContext)
  -> Result<TelematicsUnitProfile, ServiceError>

CreateTelematicsUnit(command: CreateTelematicsUnit, context: RequestContext)
  -> Result<TelematicsUnitProfile, ServiceError>

UpdateFirmwareInventory(unitId: TelematicsUnitId, firmwareVersion: FirmwareVersion, context: RequestContext)
  -> Result<TelematicsUnitProfile, ServiceError>

SetTelematicsUnitLifecycleStatus(unitId: TelematicsUnitId, status: TelematicsUnitLifecycleStatus, context: RequestContext)
  -> Result<TelematicsUnitProfile, ServiceError>

SetRemoteCommandEligibility(unitId: TelematicsUnitId, eligibility: RemoteCommandEligibility, context: RequestContext)
  -> Result<TelematicsUnitProfile, ServiceError>

ReplaceTelematicsUnitCapabilities(unitId: TelematicsUnitId, capabilities: CapabilityCode[], context: RequestContext)
  -> Result<TelematicsUnitCapabilities, ServiceError>
```

Live heartbeat and connectivity state are outside this service boundary.

