# Service Provider Master API Signatures

```text
GetServiceProvider(providerId: ServiceProviderId, context: RequestContext)
  -> Result<ServiceProviderProfile, ServiceError>

ListServiceProviders(filter: ServiceProviderFilter, page: PageRequest, context: RequestContext)
  -> Result<Page<ServiceProviderSummary>, ServiceError>

CreateServiceProvider(command: CreateServiceProvider, context: RequestContext)
  -> Result<ServiceProviderProfile, ServiceError>

UpdateServiceProvider(providerId: ServiceProviderId, changes: ServiceProviderChanges, context: RequestContext)
  -> Result<ServiceProviderProfile, ServiceError>

SetServiceProviderStatus(providerId: ServiceProviderId, status: ServiceProviderStatus, context: RequestContext)
  -> Result<ServiceProviderProfile, ServiceError>

ReplaceServiceProviderCoverage(providerId: ServiceProviderId, regions: RegionCode[], capabilities: CapabilityCode[], context: RequestContext)
  -> Result<ServiceProviderCoverage, ServiceError>
```

