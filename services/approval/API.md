# Approval API Signatures

```text
RequestHumanApproval(action: ProposedAction, context: RequestContext)
  -> Result<ApprovalRequest, ServiceError>

GetApprovalStatus(approvalId: ApprovalId, context: RequestContext)
  -> Result<ApprovalStatusView, ServiceError>

RecordApprovalDecision(approvalId: ApprovalId, decision: ApprovalDecision, context: RequestContext)
  -> Result<ApprovalStatusView, ServiceError>

ListPendingApprovals(reviewerId: ActorId, page: PageRequest, context: RequestContext)
  -> Result<Page<ApprovalRequestSummary>, ServiceError>
```

