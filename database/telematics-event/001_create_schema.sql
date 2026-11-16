CREATE SCHEMA IF NOT EXISTS telemetry;

-- Immutable accepted events. received_at is server time; observed_at is device time.
CREATE TABLE IF NOT EXISTS telemetry.events (
    event_id      varchar(64) PRIMARY KEY,
    vehicle_id    varchar(64) NOT NULL,
    event_type    varchar(48) NOT NULL,
    severity      varchar(16) NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    region_code   varchar(32) NOT NULL,
    observed_at   timestamptz NOT NULL,
    received_at   timestamptz NOT NULL DEFAULT now(),
    payload       jsonb NOT NULL,
    synthetic     boolean NOT NULL,
    content_hash  char(64) NOT NULL
);

COMMENT ON COLUMN telemetry.events.vehicle_id IS
    'Opaque Vehicle Master ID; deliberately has no cross-domain foreign key.';

CREATE INDEX IF NOT EXISTS idx_events_vehicle_time
    ON telemetry.events (vehicle_id, observed_at DESC, event_id DESC);
CREATE INDEX IF NOT EXISTS idx_events_type_time
    ON telemetry.events (event_type, observed_at DESC, event_id DESC);
CREATE INDEX IF NOT EXISTS idx_events_region_time
    ON telemetry.events (region_code, observed_at DESC, event_id DESC);

-- At most one active alert per vehicle and alert type; later events update it.
CREATE TABLE IF NOT EXISTS telemetry.alerts (
    alert_id             varchar(64) PRIMARY KEY,
    vehicle_id           varchar(64) NOT NULL,
    alert_type           varchar(48) NOT NULL,
    severity             varchar(16) NOT NULL CHECK (severity IN ('warning', 'critical')),
    status               varchar(16) NOT NULL CHECK (status IN ('active', 'cleared')),
    first_event_id       varchar(64) NOT NULL REFERENCES telemetry.events (event_id),
    last_event_id        varchar(64) NOT NULL REFERENCES telemetry.events (event_id),
    cleared_by_event_id  varchar(64) REFERENCES telemetry.events (event_id),
    raised_at            timestamptz NOT NULL,
    last_observed_at     timestamptz NOT NULL,
    updated_at           timestamptz NOT NULL DEFAULT now(),
    cleared_at           timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_alerts_active
    ON telemetry.alerts (vehicle_id, alert_type) WHERE status = 'active';
