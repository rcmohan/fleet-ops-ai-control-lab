CREATE SCHEMA IF NOT EXISTS incidents;

-- Resolved incident history. Fed by Case Management when a case is resolved, and by imports.
CREATE TABLE IF NOT EXISTS incidents.resolved_incidents (
    incident_id       varchar(64) PRIMARY KEY,
    source_case_id    varchar(64),
    vehicle_id        varchar(64) NOT NULL,
    event_type        varchar(48) NOT NULL,
    symptoms          text[] NOT NULL DEFAULT '{}',
    region_code       varchar(32),
    root_cause        text,
    resolution        text NOT NULL,
    outcome           varchar(16) NOT NULL CHECK (outcome IN ('resolved', 'workaround', 'unresolved')),
    opened_at         timestamptz NOT NULL,
    resolved_at       timestamptz NOT NULL,
    time_to_resolve_minutes integer GENERATED ALWAYS AS (
        (extract(epoch FROM resolved_at - opened_at) / 60)::integer
    ) STORED,
    content_hash      char(64) NOT NULL,
    indexed_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT resolved_after_opened CHECK (resolved_at >= opened_at)
);

CREATE INDEX IF NOT EXISTS idx_incidents_event_type ON incidents.resolved_incidents (event_type);
CREATE INDEX IF NOT EXISTS idx_incidents_symptoms ON incidents.resolved_incidents USING gin (symptoms);
CREATE INDEX IF NOT EXISTS idx_incidents_source_case
    ON incidents.resolved_incidents (source_case_id) WHERE source_case_id IS NOT NULL;
