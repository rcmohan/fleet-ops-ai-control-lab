BEGIN;

CREATE SCHEMA IF NOT EXISTS master_data;

CREATE TABLE IF NOT EXISTS master_data.vehicles (
    vehicle_id             varchar(64) PRIMARY KEY,
    synthetic_vin          varchar(32) NOT NULL UNIQUE,
    make                   varchar(80) NOT NULL,
    model                  varchar(80) NOT NULL,
    model_year             smallint NOT NULL CHECK (model_year BETWEEN 1980 AND 2200),
    powertrain_type        varchar(24) NOT NULL CHECK (
        powertrain_type IN ('gasoline', 'diesel', 'hybrid', 'plug_in_hybrid', 'battery_electric', 'hydrogen', 'other')
    ),
    region_code            varchar(32) NOT NULL,
    lifecycle_status       varchar(24) NOT NULL DEFAULT 'active' CHECK (
        lifecycle_status IN ('ordered', 'active', 'inactive', 'retired')
    ),
    service_status         varchar(24) NOT NULL DEFAULT 'in_service' CHECK (
        service_status IN ('in_service', 'maintenance', 'out_of_service', 'retired')
    ),
    warranty_status        varchar(24) NOT NULL DEFAULT 'unknown' CHECK (
        warranty_status IN ('active', 'expired', 'unknown')
    ),
    priority_level         varchar(16) NOT NULL DEFAULT 'standard' CHECK (
        priority_level IN ('low', 'standard', 'high', 'critical')
    ),
    fleet_id               varchar(64),
    telematics_unit_id     varchar(64),
    source_version         bigint NOT NULL DEFAULT 1 CHECK (source_version > 0),
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vehicles_updated_after_created CHECK (updated_at >= created_at)
);

COMMENT ON COLUMN master_data.vehicles.fleet_id IS
    'Opaque Fleet Master ID; deliberately has no cross-domain foreign key.';
COMMENT ON COLUMN master_data.vehicles.telematics_unit_id IS
    'Opaque Telematics Unit Master ID; deliberately has no cross-domain foreign key.';

CREATE INDEX IF NOT EXISTS idx_vehicles_fleet_id
    ON master_data.vehicles (fleet_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_vehicles_telematics_unit_id
    ON master_data.vehicles (telematics_unit_id)
    WHERE telematics_unit_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_vehicles_region_status
    ON master_data.vehicles (region_code, lifecycle_status);

COMMIT;

