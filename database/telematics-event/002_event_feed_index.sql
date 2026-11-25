-- The event feed (getEventFeed) reads events in the order they were received.
CREATE INDEX IF NOT EXISTS idx_events_received
    ON telemetry.events (received_at, event_id);
