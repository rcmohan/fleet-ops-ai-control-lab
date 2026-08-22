# Notification API Signatures

```text
DraftFleetNotification(fleetId: FleetId, eventId: EventId, context: RequestContext)
  -> Result<NotificationDraft, ServiceError>

SendInternalNotification(teamId: TeamId, message: NotificationMessage, context: RequestContext)
  -> Result<NotificationReceipt, ServiceError>

SendFleetManagerNotification(fleetId: FleetId, message: NotificationMessage, approvalId: ApprovalId, context: RequestContext)
  -> Result<NotificationReceipt, ServiceError>

GetNotificationStatus(notificationId: NotificationId, context: RequestContext)
  -> Result<NotificationStatus, ServiceError>
```

