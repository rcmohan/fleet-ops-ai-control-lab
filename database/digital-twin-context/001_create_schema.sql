CREATE SCHEMA IF NOT EXISTS twin;

-- Latest derived state per vehicle, rebuilt from events delivered by Telematics Event.
CREATE TABLE IF NOT EXISTS twin.vehicle_states (
    vehicle_id          varchar(64) PRIMARY KEY,
    fleet_id            varchar(64),
    health_state        varchar(16) NOT NULL CHECK (health_state IN ('healthy', 'warning', 'critical')),
    connectivity_state  varchar(16) NOT NULL CHECK (
        connectivity_state IN ('connected', 'degraded', 'disconnected')
    ),
    odometer_km         numeric(12, 1),
    battery_voltage     numeric(5, 2),
    last_location       jsonb,
    issues              jsonb NOT NULL DEFAULT '{}'::jsonb,
    observed_at         timestamptz NOT NULL,
    state_version       bigint NOT NULL DEFAULT 1,
    updated_at          timestamptz NOT NULL DEFAULT now()
);

COMMENT ON COLUMN twin.vehicle_states.fleet_id IS
    'Copied from Vehicle Master when each event is applied; no cross-domain foreign key.';

CREATE INDEX IF NOT EXISTS idx_vehicle_states_fleet ON twin.vehicle_states (fleet_id);

-- Every delivered event, so redelivery is idempotent and impact can be traced.
CREATE TABLE IF NOT EXISTS twin.applied_events (
    event_id            varchar(64) PRIMARY KEY,
    vehicle_id          varchar(64) NOT NULL,
    fleet_id            varchar(64),
    event_type          varchar(48) NOT NULL,
    severity            varchar(16) NOT NULL,
    observed_at         timestamptz NOT NULL,
    payload             jsonb NOT NULL,
    outcome             varchar(16) NOT NULL CHECK (outcome IN ('applied', 'stale')),
    state_version       bigint NOT NULL,
    health_state_after  varchar(16) NOT NULL,
    applied_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_applied_events_vehicle
    ON twin.applied_events (vehicle_id, observed_at DESC);
