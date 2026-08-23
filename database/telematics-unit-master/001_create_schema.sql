BEGIN;

CREATE SCHEMA IF NOT EXISTS master_data;

CREATE TABLE IF NOT EXISTS master_data.telematics_units (
    unit_id                       varchar(64) PRIMARY KEY,
    serial_number                 varchar(96) NOT NULL UNIQUE,
    hardware_model                varchar(80) NOT NULL,
    firmware_version              varchar(64) NOT NULL,
    activation_date               date,
    network_carrier               varchar(80),
    lifecycle_status              varchar(24) NOT NULL DEFAULT 'inventory' CHECK (
        lifecycle_status IN ('inventory', 'active', 'suspended', 'decommissioned')
    ),
    remote_command_eligibility    varchar(24) NOT NULL DEFAULT 'not_eligible' CHECK (
        remote_command_eligibility IN ('eligible', 'approval_required', 'not_eligible')
    ),
    source_version                bigint NOT NULL DEFAULT 1 CHECK (source_version > 0),
    created_at                    timestamptz NOT NULL DEFAULT now(),
    updated_at                    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT telematics_units_updated_after_created CHECK (updated_at >= created_at)
);

CREATE TABLE IF NOT EXISTS master_data.telematics_unit_capabilities (
    unit_id          varchar(64) NOT NULL,
    capability_code varchar(64) NOT NULL,
    enabled          boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (unit_id, capability_code),
    CONSTRAINT fk_capability_unit FOREIGN KEY (unit_id)
        REFERENCES master_data.telematics_units (unit_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_telematics_units_status
    ON master_data.telematics_units (lifecycle_status);

COMMIT;

