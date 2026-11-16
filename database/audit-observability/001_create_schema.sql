CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS audit.audit_events (
    audit_event_id  varchar(64) PRIMARY KEY,
    trace_id        varchar(64) NOT NULL,
    category        varchar(32) NOT NULL CHECK (category IN (
        'agent_trace', 'tool_call', 'policy_decision', 'recommendation',
        'human_decision', 'action_outcome'
    )),
    event_type      varchar(64) NOT NULL,
    occurred_at     timestamptz NOT NULL,
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    attributes      jsonb NOT NULL,
    payload         jsonb NOT NULL,
    content_hash    char(64) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_trace
    ON audit.audit_events (trace_id, occurred_at, audit_event_id);

-- Append-only: the service's own role cannot change or remove recorded events either.
CREATE OR REPLACE FUNCTION audit.reject_changes() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit events are append-only';
END;
$$;

CREATE TRIGGER audit_events_append_only
    BEFORE UPDATE OR DELETE ON audit.audit_events
    FOR EACH ROW EXECUTE FUNCTION audit.reject_changes();

CREATE TRIGGER audit_events_no_truncate
    BEFORE TRUNCATE ON audit.audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit.reject_changes();
