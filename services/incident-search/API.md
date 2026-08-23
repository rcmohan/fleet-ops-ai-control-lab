# Prior Incident Search API Signatures

```text
SearchSimilarIncidents(signature: EventSignature, page: PageRequest, context: RequestContext)
  -> Result<Page<SimilarIncident>, ServiceError>

GetIncidentResolution(incidentId: IncidentId, context: RequestContext)
  -> Result<IncidentResolution, ServiceError>

GetCommonResolutionPatterns(eventType: EventType, context: RequestContext)
  -> Result<ResolutionPattern[], ServiceError>

GetHistoricalResolutionTime(eventType: EventType, context: RequestContext)
  -> Result<ResolutionTimeStatistics, ServiceError>
```

