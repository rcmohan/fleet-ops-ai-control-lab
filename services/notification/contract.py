from fleetops_runtime import Operation, ServiceContract


CONTRACT = ServiceContract(
    slug="notification",
    title="Notification Service",
    description="Synthetic notification drafts, delivery attempts, and status with approval controls.",
    operations=(
        Operation(
            method="POST",
            path="/v1/notifications/fleet-drafts",
            operation_id="draftFleetNotification",
            summary="Draft a fleet notification",
            response={
                "notificationId": "ntf_demo_001",
                "fleetId": "flt_demo_001",
                "eventId": "evt_demo_001",
                "channel": "email",
                "status": "draft",
                "message": "Synthetic fleet notification draft",
            },
            request={"fleetId": "flt_demo_001", "eventId": "evt_demo_001"},
        ),
        Operation(
            method="POST",
            path="/v1/notifications/internal",
            operation_id="sendInternalNotification",
            summary="Send an internal notification",
            response={
                "notificationId": "ntf_demo_002",
                "status": "delivered",
                "channel": "internal",
                "deliveredAt": "2026-08-22T12:00:00Z",
            },
            request={
                "teamId": "team_ops",
                "message": "Synthetic internal notification",
            },
        ),
        Operation(
            method="POST",
            path="/v1/notifications/fleet-manager",
            operation_id="sendFleetManagerNotification",
            summary="Send an approved fleet-manager notification",
            response={
                "notificationId": "ntf_demo_003",
                "status": "delivered",
                "channel": "email",
                "approvalId": "apr_demo_001",
                "deliveredAt": "2026-08-22T12:00:00Z",
            },
            request={
                "fleetId": "flt_demo_001",
                "message": "Synthetic customer notification",
                "approvalId": "apr_demo_001",
            },
        ),
        Operation(
            method="GET",
            path="/v1/notifications/{notification_id}",
            operation_id="getNotificationStatus",
            summary="Get notification status",
            response={
                "notificationId": "{notification_id}",
                "status": "delivered",
                "channel": "email",
                "attemptCount": 1,
                "updatedAt": "2026-08-22T12:00:00Z",
            },
        ),
    ),
)
