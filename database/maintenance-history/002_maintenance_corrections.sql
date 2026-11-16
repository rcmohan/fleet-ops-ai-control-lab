-- Corrections are appended, never edited; maintenance_records holds the corrected current view.
CREATE TABLE IF NOT EXISTS master_data.maintenance_corrections (
    correction_id     varchar(64) PRIMARY KEY,
    maintenance_id    varchar(64) NOT NULL,
    reason            text NOT NULL,
    changes           jsonb NOT NULL,
    previous_values   jsonb NOT NULL,
    resulting_version bigint NOT NULL,
    corrected_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_correction_record FOREIGN KEY (maintenance_id)
        REFERENCES master_data.maintenance_records (maintenance_id)
);

CREATE INDEX IF NOT EXISTS idx_corrections_record
    ON master_data.maintenance_corrections (maintenance_id, corrected_at);

CREATE OR REPLACE FUNCTION master_data.reject_correction_changes() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'maintenance corrections are append-only';
END;
$$;

CREATE TRIGGER maintenance_corrections_append_only
    BEFORE UPDATE OR DELETE ON master_data.maintenance_corrections
    FOR EACH ROW EXECUTE FUNCTION master_data.reject_correction_changes();
