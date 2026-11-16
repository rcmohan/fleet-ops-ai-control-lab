ALTER TABLE master_data.fleets
    ADD COLUMN IF NOT EXISTS contract_effective_date date NOT NULL DEFAULT current_date;

-- Response targets per SLA classification. Synthetic values for demonstration only.
CREATE TABLE IF NOT EXISTS master_data.sla_levels (
    sla_level                varchar(24) PRIMARY KEY,
    response_target_minutes  integer NOT NULL CHECK (response_target_minutes > 0)
);

INSERT INTO master_data.sla_levels (sla_level, response_target_minutes) VALUES
    ('standard', 240),
    ('enhanced', 120),
    ('mission_critical', 30)
ON CONFLICT (sla_level) DO NOTHING;

ALTER TABLE master_data.fleets
    ADD CONSTRAINT fk_fleet_sla_level FOREIGN KEY (sla_level)
        REFERENCES master_data.sla_levels (sla_level);

CREATE INDEX IF NOT EXISTS idx_fleet_regions_region
    ON master_data.fleet_operating_regions (region_code);
