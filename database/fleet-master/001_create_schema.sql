BEGIN;

CREATE SCHEMA IF NOT EXISTS master_data;

CREATE TABLE IF NOT EXISTS master_data.fleets (
    fleet_id                       varchar(64) PRIMARY KEY,
    customer_name                  varchar(160) NOT NULL,
    industry_code                  varchar(64) NOT NULL,
    declared_fleet_size            integer NOT NULL DEFAULT 0 CHECK (declared_fleet_size >= 0),
    contract_tier                  varchar(24) NOT NULL CHECK (
        contract_tier IN ('basic', 'standard', 'premium', 'enterprise')
    ),
    sla_level                      varchar(24) NOT NULL CHECK (
        sla_level IN ('standard', 'enhanced', 'mission_critical')
    ),
    priority_level                 varchar(16) NOT NULL DEFAULT 'standard' CHECK (
        priority_level IN ('low', 'standard', 'high', 'critical')
    ),
    preferred_service_provider_id  varchar(64),
    lifecycle_status               varchar(24) NOT NULL DEFAULT 'active' CHECK (
        lifecycle_status IN ('prospect', 'active', 'suspended', 'closed')
    ),
    source_version                 bigint NOT NULL DEFAULT 1 CHECK (source_version > 0),
    created_at                     timestamptz NOT NULL DEFAULT now(),
    updated_at                     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fleets_updated_after_created CHECK (updated_at >= created_at)
);

COMMENT ON COLUMN master_data.fleets.preferred_service_provider_id IS
    'Opaque Service Provider Master ID; deliberately has no cross-domain foreign key.';

CREATE TABLE IF NOT EXISTS master_data.fleet_operating_regions (
    fleet_id       varchar(64) NOT NULL,
    region_code    varchar(32) NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (fleet_id, region_code),
    CONSTRAINT fk_operating_region_fleet FOREIGN KEY (fleet_id)
        REFERENCES master_data.fleets (fleet_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS master_data.fleet_escalation_contacts (
    contact_id      varchar(64) PRIMARY KEY,
    fleet_id        varchar(64) NOT NULL,
    contact_name    varchar(120) NOT NULL,
    contact_role    varchar(80) NOT NULL,
    email_address   varchar(254),
    phone_number    varchar(40),
    escalation_rank smallint NOT NULL DEFAULT 1 CHECK (escalation_rank > 0),
    active          boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT escalation_contact_method_required CHECK (
        email_address IS NOT NULL OR phone_number IS NOT NULL
    ),
    CONSTRAINT fk_escalation_contact_fleet FOREIGN KEY (fleet_id)
        REFERENCES master_data.fleets (fleet_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fleets_provider_id
    ON master_data.fleets (preferred_service_provider_id);
CREATE INDEX IF NOT EXISTS idx_fleet_contacts_fleet_rank
    ON master_data.fleet_escalation_contacts (fleet_id, escalation_rank);

COMMIT;

