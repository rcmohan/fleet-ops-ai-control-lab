# Policy and Playbook API Signatures

```text
SearchPlaybooks(query: PlaybookQuery, page: PageRequest, context: RequestContext)
  -> Result<Page<PlaybookSearchResult>, ServiceError>

GetPolicy(policyId: PolicyId, version: PolicyVersion?, context: RequestContext)
  -> Result<PolicyDocument, ServiceError>

GetEscalationRules(eventType: EventType, severity: Severity, context: RequestContext)
  -> Result<EscalationRule[], ServiceError>

GetActionEligibility(actionType: ActionType, riskLevel: RiskLevel, context: RequestContext)
  -> Result<ActionEligibility, ServiceError>

GetRequiredApproval(actionType: ActionType, context: RequestContext)
  -> Result<ApprovalRequirement, ServiceError>
```

