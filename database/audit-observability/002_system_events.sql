-- Deterministic services (for example signal-correlation) record their own transitions.
ALTER TABLE audit.audit_events DROP CONSTRAINT IF EXISTS audit_events_category_check;
ALTER TABLE audit.audit_events ADD CONSTRAINT audit_events_category_check CHECK (category IN (
    'agent_trace', 'tool_call', 'policy_decision', 'recommendation',
    'human_decision', 'action_outcome', 'system_event'
));
