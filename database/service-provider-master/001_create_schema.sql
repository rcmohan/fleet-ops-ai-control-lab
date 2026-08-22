BEGIN;

CREATE SCHEMA IF NOT EXISTS master_data;

CREATE TABLE IF NOT EXISTS master_data.service_providers (
    provider_id                   varchar(64) PRIMARY KEY,
    provider_name                 varchar(160) NOT NULL,
    lifecycle_status              varchar(24) NOT NULL DEFAULT 'active' CHECK (
        lifecycle_status IN ('active', 'at_capacity', 'suspended', 'closed')
    ),
    average_response_minutes      integer CHECK (average_response_minutes IS NULL OR average_response_minutes >= 0),
    daily_capacity                integer CHECK (daily_capacity IS NULL OR daily_capacity >= 0),
    source_version                bigint NOT NULL DEFAULT 1 CHECK (source_version > 0),
    created_at                    timestamptz NOT NULL DEFAULT now(),
    updated_at                    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT service_providers_updated_after_created CHECK (updated_at >= created_at)
);

CREATE TABLE IF NOT EXISTS master_data.service_provider_regions (
    provider_id    varchar(64) NOT NULL,
    region_code    varchar(32) NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provider_id, region_code),
    CONSTRAINT fk_provider_region_provider FOREIGN KEY (provider_id)
        REFERENCES master_data.service_providers (provider_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS master_data.service_provider_capabilities (
    provider_id     varchar(64) NOT NULL,
    capability_code varchar(64) NOT NULL,
    active           boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provider_id, capability_code),
    CONSTRAINT fk_provider_capability_provider FOREIGN KEY (provider_id)
        REFERENCES master_data.service_providers (provider_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_service_providers_status
    ON master_data.service_providers (lifecycle_status);

COMMIT;

