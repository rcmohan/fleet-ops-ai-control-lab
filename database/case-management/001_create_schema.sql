CREATE SCHEMA IF NOT EXISTS cases;

CREATE TABLE IF NOT EXISTS cases.service_cases (
    case_id            varchar(64) PRIMARY KEY,
    vehicle_id         varchar(64) NOT NULL,
    recommendation_id  varchar(64),
    summary            text NOT NULL,
    event_type         varchar(48),
    symptoms           text[] NOT NULL DEFAULT '{}',
    region_code        varchar(32),
    status             varchar(16) NOT NULL CHECK (
        status IN ('open', 'in_progress', 'resolved', 'closed', 'cancelled')
    ),
    assigned_team_id   varchar(64),
    audit_trace_id     varchar(64),
    root_cause         text,
    resolution         text,
    resolution_outcome varchar(16) CHECK (
        resolution_outcome IS NULL OR resolution_outcome IN ('resolved', 'workaround', 'unresolved')
    ),
    resolved_at        timestamptz,
    source_version     bigint NOT NULL DEFAULT 1 CHECK (source_version > 0),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT in_progress_needs_team CHECK (status <> 'in_progress' OR assigned_team_id IS NOT NULL),
    CONSTRAINT resolved_needs_resolution CHECK (
        status NOT IN ('resolved', 'closed') OR resolution IS NOT NULL
    )
);

COMMENT ON COLUMN cases.service_cases.vehicle_id IS
    'Opaque Vehicle Master ID; deliberately has no cross-domain foreign key.';

-- One case per recommendation, so a retried recommendation cannot open a second case.
CREATE UNIQUE INDEX IF NOT EXISTS uq_cases_recommendation
    ON cases.service_cases (recommendation_id) WHERE recommendation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cases_vehicle ON cases.service_cases (vehicle_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cases_team_status ON cases.service_cases (assigned_team_id, status);

CREATE TABLE IF NOT EXISTS cases.case_history (
    history_id   bigserial PRIMARY KEY,
    case_id      varchar(64) NOT NULL REFERENCES cases.service_cases (case_id),
    change_type  varchar(32) NOT NULL,
    from_value   varchar(64),
    to_value     varchar(64),
    comment      text,
    changed_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cases.case_attachments (
    attachment_id      varchar(64) PRIMARY KEY,
    case_id            varchar(64) NOT NULL REFERENCES cases.service_cases (case_id),
    attachment_type    varchar(32) NOT NULL,
    recommendation_id  varchar(64),
    summary            text NOT NULL,
    trace_id           varchar(64),
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_case_attachments_case ON cases.case_attachments (case_id, created_at);
