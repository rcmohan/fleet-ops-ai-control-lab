CREATE SCHEMA IF NOT EXISTS correlation;

-- Non-info telematics events forwarded by telematics-event's outbox.
CREATE TABLE IF NOT EXISTS correlation.signals (
    event_id     varchar(64) PRIMARY KEY,
    vehicle_id   varchar(64) NOT NULL,
    event_type   varchar(48) NOT NULL,
    severity     varchar(16) NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    observed_at  timestamptz NOT NULL,
    payload      jsonb NOT NULL DEFAULT '{}',
    received_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signals_vehicle_time
    ON correlation.signals (vehicle_id, observed_at, event_id);

CREATE TABLE IF NOT EXISTS correlation.incidents (
    incident_id        varchar(64) PRIMARY KEY,
    rule_id            varchar(64) NOT NULL,
    vehicle_id         varchar(64) NOT NULL,
    status             varchar(24) NOT NULL CHECK (status IN (
        'detected', 'awaiting_approval', 'case_opened', 'rejected', 'approval_expired',
        'blocked', 'failed', 'closed'
    )),
    trace_id           varchar(64) NOT NULL,
    first_observed_at  timestamptz NOT NULL,
    last_observed_at   timestamptz NOT NULL,
    trigger_event_ids  text[] NOT NULL,
    scored_event_id    varchar(64) NOT NULL,
    risk_score         numeric(5, 1),
    risk_level         varchar(16),
    policy_decision    varchar(24),
    policy_id          varchar(64),
    policy_version     varchar(16),
    reviewer_role      varchar(64),
    approval_id        varchar(64),
    case_id            varchar(64),
    attempts           integer NOT NULL DEFAULT 0,
    next_attempt_at    timestamptz NOT NULL DEFAULT now(),
    last_error         text,
    closed_reason      text,
    source_version     bigint NOT NULL DEFAULT 1 CHECK (source_version > 0),
    detected_at        timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT case_opened_has_case CHECK (status <> 'case_opened' OR case_id IS NOT NULL),
    CONSTRAINT waiting_has_approval CHECK (status <> 'awaiting_approval' OR approval_id IS NOT NULL)
);

-- At most one active incident per vehicle and rule; new matches attach to it.
CREATE UNIQUE INDEX IF NOT EXISTS uq_incidents_active
    ON correlation.incidents (vehicle_id, rule_id)
    WHERE status IN ('detected', 'awaiting_approval', 'case_opened');

CREATE INDEX IF NOT EXISTS idx_incidents_due
    ON correlation.incidents (next_attempt_at)
    WHERE status IN ('detected', 'awaiting_approval');

CREATE INDEX IF NOT EXISTS idx_incidents_detected
    ON correlation.incidents (detected_at DESC, incident_id DESC);

-- An event belongs to at most one incident, so it can never trigger a second one.
CREATE TABLE IF NOT EXISTS correlation.incident_events (
    event_id     varchar(64) PRIMARY KEY REFERENCES correlation.signals (event_id),
    incident_id  varchar(64) NOT NULL REFERENCES correlation.incidents (incident_id),
    role         varchar(16) NOT NULL CHECK (role IN ('trigger', 'supporting')),
    step_name    varchar(48)
);

CREATE INDEX IF NOT EXISTS idx_incident_events_incident
    ON correlation.incident_events (incident_id);

CREATE TABLE IF NOT EXISTS correlation.incident_steps (
    step_id      bigserial PRIMARY KEY,
    incident_id  varchar(64) NOT NULL REFERENCES correlation.incidents (incident_id),
    step         varchar(48) NOT NULL,
    detail       jsonb NOT NULL DEFAULT '{}',
    at           timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_incident_steps_incident
    ON correlation.incident_steps (incident_id, step_id);
