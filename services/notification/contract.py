from fleetops_runtime import Operation, ServiceContract


CONTRACT = ServiceContract(
    slug="notification",
    title="Notification Service",
    description="Synthetic notification drafts, delivery attempts, and status with approval controls.",
    operations=(
        Operation("POST", "/v1/notifications/fleet-drafts", "draftFleetNotification", "Draft a fleet notification", {"notificationId": "ntf_demo_001", "fleetId": "flt_demo_001", "eventId": "evt_demo_001", "channel": "email", "status": "draft", "message": "Synthetic fleet notification draft"}, {"fleetId": "flt_demo_001", "eventId": "evt_demo_001"}),
        Operation("POST", "/v1/notifications/internal", "sendInternalNotification", "Send an internal notification", {"notificationId": "ntf_demo_002", "status": "delivered", "channel": "internal", "deliveredAt": "2026-08-22T12:00:00Z"}, {"teamId": "team_ops", "message": "Synthetic internal notification"}),
        Operation("POST", "/v1/notifications/fleet-manager", "sendFleetManagerNotification", "Send an approved fleet-manager notification", {"notificationId": "ntf_demo_003", "status": "delivered", "channel": "email", "approvalId": "apr_demo_001", "deliveredAt": "2026-08-22T12:00:00Z"}, {"fleetId": "flt_demo_001", "message": "Synthetic customer notification", "approvalId": "apr_demo_001"}),
        Operation("GET", "/v1/notifications/{notification_id}", "getNotificationStatus", "Get notification status", {"notificationId": "{notification_id}", "status": "delivered", "channel": "email", "attemptCount": 1, "updatedAt": "2026-08-22T12:00:00Z"}),
    ),
)

