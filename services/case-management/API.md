# Case Management API Signatures

```text
CreateServiceCase(vehicleId: VehicleId, recommendation: RecommendationReference, context: RequestContext)
  -> Result<ServiceCase, ServiceError>

UpdateCase(caseId: CaseId, status: CaseStatus, context: RequestContext)
  -> Result<ServiceCase, ServiceError>

AssignCase(caseId: CaseId, teamId: TeamId, context: RequestContext)
  -> Result<ServiceCase, ServiceError>

AttachAgentSummary(caseId: CaseId, summary: AgentSummary, context: RequestContext)
  -> Result<CaseAttachment, ServiceError>

GetCaseStatus(caseId: CaseId, context: RequestContext)
  -> Result<CaseStatusView, ServiceError>
```

