CREATE SCHEMA IF NOT EXISTS policy;

CREATE TABLE IF NOT EXISTS policy.policies (
    policy_id   varchar(64) NOT NULL,
    version     varchar(16) NOT NULL,
    title       varchar(200) NOT NULL,
    status      varchar(16) NOT NULL CHECK (status IN ('draft', 'active', 'retired')),
    content     text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (policy_id, version)
);

-- Only one active version per policy.
CREATE UNIQUE INDEX IF NOT EXISTS uq_policies_active
    ON policy.policies (policy_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS policy.playbooks (
    playbook_id  varchar(64) NOT NULL,
    version      varchar(16) NOT NULL,
    title        varchar(200) NOT NULL,
    event_types  text[] NOT NULL DEFAULT '{}',
    body         text NOT NULL,
    status       varchar(16) NOT NULL CHECK (status IN ('draft', 'active', 'retired')),
    -- Event types are matched exactly in queries; array_to_string is not immutable,
    -- so it cannot appear in a generated column.
    search       tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', title), 'A') ||
        setweight(to_tsvector('english', body), 'B')
    ) STORED,
    PRIMARY KEY (playbook_id, version)
);

CREATE INDEX IF NOT EXISTS idx_playbooks_search ON policy.playbooks USING gin (search);

-- event_type '*' matches every event type.
CREATE TABLE IF NOT EXISTS policy.escalation_rules (
    rule_id                  varchar(64) PRIMARY KEY,
    event_type               varchar(48) NOT NULL,
    severity                 varchar(16) NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    target_team              varchar(64) NOT NULL,
    response_target_minutes  integer NOT NULL CHECK (response_target_minutes > 0),
    policy_id                varchar(64) NOT NULL,
    active                   boolean NOT NULL DEFAULT true
);

-- approval_mode: none = may run autonomously up to max_autonomous_risk;
-- required = needs a reviewer above that limit; blocked = never permitted.
CREATE TABLE IF NOT EXISTS policy.action_controls (
    action_type             varchar(64) PRIMARY KEY,
    approval_mode           varchar(16) NOT NULL CHECK (approval_mode IN ('none', 'required', 'blocked')),
    max_autonomous_risk     varchar(16) CHECK (
        max_autonomous_risk IS NULL OR max_autonomous_risk IN ('low', 'medium', 'high', 'critical')
    ),
    required_reviewer_role  varchar(64),
    policy_id               varchar(64) NOT NULL,
    policy_version          varchar(16) NOT NULL,
    CONSTRAINT reviewer_for_required CHECK (
        approval_mode <> 'required' OR required_reviewer_role IS NOT NULL
    )
);
