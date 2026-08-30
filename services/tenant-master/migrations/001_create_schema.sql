CREATE SCHEMA IF NOT EXISTS master_data;

CREATE TABLE IF NOT EXISTS master_data.records (
    tenant_id      varchar(64) NOT NULL,
    record_id      varchar(64) NOT NULL,
    natural_key    varchar(160),
    document       jsonb NOT NULL,
    source_version bigint NOT NULL DEFAULT 1 CHECK (source_version > 0),
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, record_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_records_tenant_natural_key
    ON master_data.records (tenant_id, natural_key)
    WHERE natural_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_records_tenant_updated
    ON master_data.records (tenant_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS master_data.idempotency_results (
    tenant_id       varchar(64) NOT NULL,
    operation       varchar(160) NOT NULL,
    idempotency_key varchar(160) NOT NULL,
    response        jsonb NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, operation, idempotency_key)
);
