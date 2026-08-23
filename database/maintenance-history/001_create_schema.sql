BEGIN;

CREATE SCHEMA IF NOT EXISTS master_data;

CREATE TABLE IF NOT EXISTS master_data.maintenance_records (
    maintenance_id       varchar(64) PRIMARY KEY,
    vehicle_id           varchar(64) NOT NULL,
    service_provider_id  varchar(64),
    event_type           varchar(32) NOT NULL CHECK (
        event_type IN ('inspection', 'preventive', 'repair', 'recall', 'diagnostic', 'other')
    ),
    service_status       varchar(24) NOT NULL CHECK (
        service_status IN ('scheduled', 'in_progress', 'completed', 'cancelled')
    ),
    opened_at            timestamptz NOT NULL,
    completed_at         timestamptz,
    odometer_km          numeric(12, 1) CHECK (odometer_km IS NULL OR odometer_km >= 0),
    summary              text NOT NULL,
    resolution           text,
    source_reference     varchar(128),
    source_version       bigint NOT NULL DEFAULT 1 CHECK (source_version > 0),
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT maintenance_completion_order CHECK (
        completed_at IS NULL OR completed_at >= opened_at
    ),
    CONSTRAINT maintenance_updated_after_created CHECK (updated_at >= created_at)
);

COMMENT ON COLUMN master_data.maintenance_records.vehicle_id IS
    'Opaque Vehicle Master ID; deliberately has no cross-domain foreign key.';
COMMENT ON COLUMN master_data.maintenance_records.service_provider_id IS
    'Opaque Service Provider Master ID; deliberately has no cross-domain foreign key.';

CREATE INDEX IF NOT EXISTS idx_maintenance_vehicle_opened
    ON master_data.maintenance_records (vehicle_id, opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_maintenance_provider_opened
    ON master_data.maintenance_records (service_provider_id, opened_at DESC);

COMMIT;

