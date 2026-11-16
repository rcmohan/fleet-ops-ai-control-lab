CREATE SCHEMA IF NOT EXISTS notifications;

-- Delivery is simulated: no message leaves the lab. A delivered row means the synthetic
-- channel accepted it.
CREATE TABLE IF NOT EXISTS notifications.notifications (
    notification_id  varchar(64) PRIMARY KEY,
    kind             varchar(24) NOT NULL CHECK (kind IN ('fleet_draft', 'internal', 'fleet_manager')),
    channel          varchar(16) NOT NULL CHECK (channel IN ('email', 'internal')),
    status           varchar(16) NOT NULL CHECK (status IN ('draft', 'delivered', 'failed')),
    fleet_id         varchar(64),
    event_id         varchar(64),
    team_id          varchar(64),
    approval_id      varchar(64),
    message          text NOT NULL,
    attempt_count    integer NOT NULL DEFAULT 0,
    delivered_at     timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- An approval authorizes exactly one fleet-manager message.
CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_approval
    ON notifications.notifications (approval_id) WHERE approval_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS notifications.delivery_attempts (
    attempt_id       bigserial PRIMARY KEY,
    notification_id  varchar(64) NOT NULL REFERENCES notifications.notifications (notification_id),
    outcome          varchar(16) NOT NULL CHECK (outcome IN ('delivered', 'failed')),
    detail           text,
    attempted_at     timestamptz NOT NULL DEFAULT now()
);
