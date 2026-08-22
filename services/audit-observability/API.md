# Audit and Observability API Signatures

```text
RecordAgentTrace(event: AgentTraceEvent, context: RequestContext)
  -> Result<AuditReceipt, ServiceError>

RecordToolCall(event: ToolCallEvent, context: RequestContext)
  -> Result<AuditReceipt, ServiceError>

RecordPolicyDecision(event: PolicyDecisionEvent, context: RequestContext)
  -> Result<AuditReceipt, ServiceError>

RecordRecommendation(event: RecommendationEvent, context: RequestContext)
  -> Result<AuditReceipt, ServiceError>

RecordHumanDecision(event: HumanDecisionEvent, context: RequestContext)
  -> Result<AuditReceipt, ServiceError>

RecordActionOutcome(event: ActionOutcomeEvent, context: RequestContext)
  -> Result<AuditReceipt, ServiceError>

GetTrace(traceId: TraceId, context: RequestContext)
  -> Result<CorrelatedTrace, ServiceError>
```

Record operations are append-only and require caller-supplied event IDs for idempotency.

