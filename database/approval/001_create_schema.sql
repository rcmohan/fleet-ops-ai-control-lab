CREATE SCHEMA IF NOT EXISTS approvals;

-- Synthetic reviewer directory. Real deployments take identity from an authenticated access layer.
CREATE TABLE IF NOT EXISTS approvals.reviewers (
    reviewer_id   varchar(64) PRIMARY KEY,
    display_name  varchar(120) NOT NULL,
    role          varchar(64) NOT NULL,
    active        boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS approvals.approval_requests (
    approval_id              varchar(64) PRIMARY KEY,
    action_id                varchar(64) NOT NULL,
    action_type              varchar(64) NOT NULL,
    risk_level               varchar(16) NOT NULL CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    evidence_trace_id        varchar(64) NOT NULL,
    requested_reviewer_role  varchar(64) NOT NULL,
    status                   varchar(16) NOT NULL CHECK (
        status IN ('pending', 'approved', 'rejected', 'expired')
    ),
    reviewer_id              varchar(64) REFERENCES approvals.reviewers (reviewer_id),
    comments                 text,
    requested_at             timestamptz NOT NULL DEFAULT now(),
    expires_at               timestamptz NOT NULL,
    decided_at               timestamptz,
    CONSTRAINT decision_has_reviewer CHECK (
        status NOT IN ('approved', 'rejected') OR (reviewer_id IS NOT NULL AND decided_at IS NOT NULL)
    ),
    CONSTRAINT expiry_after_request CHECK (expires_at > requested_at)
);

-- An action can have only one approval request awaiting a decision.
CREATE UNIQUE INDEX IF NOT EXISTS uq_approvals_pending_action
    ON approvals.approval_requests (action_id) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_approvals_role_status
    ON approvals.approval_requests (requested_reviewer_role, status, requested_at);

INSERT INTO approvals.reviewers (reviewer_id, display_name, role) VALUES
    ('reviewer_ops_001', 'Synthetic Operations Manager', 'operations_manager'),
    ('reviewer_safety_001', 'Synthetic Safety Officer', 'safety_officer')
ON CONFLICT DO NOTHING;
