"""PostgreSQL access: connection pool, ordered migrations, and small query helpers."""

from __future__ import annotations

import hashlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

# Tables every service database gets, owned by the runtime rather than the domain.
RUNTIME_SCHEMA = """
CREATE SCHEMA IF NOT EXISTS runtime;

CREATE TABLE IF NOT EXISTS runtime.schema_migrations (
    version     varchar(128) PRIMARY KEY,
    checksum    char(64) NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runtime.idempotency_keys (
    operation_id     varchar(128) NOT NULL,
    idempotency_key  varchar(128) NOT NULL,
    request_hash     char(64) NOT NULL,
    response         jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (operation_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS runtime.outbox (
    message_id       bigserial PRIMARY KEY,
    destination      varchar(64) NOT NULL,
    path             varchar(256) NOT NULL,
    payload          jsonb NOT NULL,
    status           varchar(16) NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'delivered', 'dead')
    ),
    attempts         integer NOT NULL DEFAULT 0,
    next_attempt_at  timestamptz NOT NULL DEFAULT now(),
    last_error       text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    delivered_at     timestamptz
);

CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON runtime.outbox (next_attempt_at) WHERE status = 'pending';
"""

MIGRATION_LOCK = "fleetops-schema-migrations"


class MigrationError(RuntimeError):
    pass


def database_url_for(slug: str) -> str:
    """FLEETOPS_DATABASE_URL wins; otherwise one database and role per service, named after it."""
    explicit = os.environ.get("FLEETOPS_DATABASE_URL")
    if explicit:
        return explicit
    name = "fleetops_" + slug.replace("-", "_")
    host = os.environ.get("FLEETOPS_DB_HOST", "localhost")
    port = os.environ.get("FLEETOPS_DB_PORT", "5432")
    password = os.environ.get("FLEETOPS_DB_PASSWORD", "fleetops-dev")
    return f"postgresql://{name}:{password}@{host}:{port}/{name}"


def _checksum(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode()).hexdigest()


class Database:
    def __init__(
        self, url: str, migrations_dir: Path | None, *, min_size: int = 1, max_size: int = 5
    ) -> None:
        self.url = url
        self.migrations_dir = migrations_dir
        self.pool = AsyncConnectionPool(
            url,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        self._opened = False

    async def open(self, timeout: float = 30.0) -> None:
        if self._opened:
            return
        await self.migrate()
        await self.pool.open(wait=True, timeout=timeout)
        self._opened = True

    async def close(self) -> None:
        if self._opened:
            await self.pool.close()
            self._opened = False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        async with self.pool.connection() as conn:
            async with conn.transaction():
                yield conn

    async def ping(self) -> bool:
        try:
            async with self.pool.connection(timeout=2.0) as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def migrate(self) -> list[str]:
        """Apply runtime tables, then each unapplied NNN_*.sql file in its own transaction."""
        applied_now: list[str] = []
        async with await AsyncConnection.connect(self.url, autocommit=True) as conn:
            await conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (MIGRATION_LOCK,))
            try:
                await conn.execute(RUNTIME_SCHEMA)
                cursor = await conn.execute(
                    "SELECT version, checksum FROM runtime.schema_migrations"
                )
                applied = {version: checksum for version, checksum in await cursor.fetchall()}
                files = sorted(self.migrations_dir.glob("*.sql")) if self.migrations_dir else []
                for path in files:
                    text = path.read_text(encoding="utf-8")
                    checksum = _checksum(text)
                    if path.stem in applied:
                        if applied[path.stem] != checksum:
                            raise MigrationError(
                                f"{path.name} changed after it was applied; add a new migration instead"
                            )
                        continue
                    async with conn.transaction():
                        await conn.execute(text)
                        await conn.execute(
                            "INSERT INTO runtime.schema_migrations (version, checksum) VALUES (%s, %s)",
                            (path.stem, checksum),
                        )
                    applied_now.append(path.stem)
            finally:
                await conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (MIGRATION_LOCK,))
        return applied_now


async def fetch_one(conn: AsyncConnection, query: Any, params: Any = None) -> dict[str, Any] | None:
    cursor = await conn.execute(query, params)
    return await cursor.fetchone()


async def fetch_all(conn: AsyncConnection, query: Any, params: Any = None) -> list[dict[str, Any]]:
    cursor = await conn.execute(query, params)
    return await cursor.fetchall()


async def update_versioned(
    conn: AsyncConnection,
    table: str,
    key_column: str,
    key: str,
    values: dict[str, Any],
) -> dict[str, Any] | None:
    """UPDATE schema.table SET <values>, source_version+1, updated_at=now() RETURNING *."""
    schema, name = table.split(".")
    assignments = [
        sql.SQL("{} = {}").format(sql.Identifier(column), sql.Placeholder())
        for column in values
    ]
    assignments.append(sql.SQL("source_version = source_version + 1"))
    assignments.append(sql.SQL("updated_at = now()"))
    query = sql.SQL("UPDATE {} SET {} WHERE {} = {} RETURNING *").format(
        sql.Identifier(schema, name),
        sql.SQL(", ").join(assignments),
        sql.Identifier(key_column),
        sql.Placeholder(),
    )
    return await fetch_one(conn, query, [*values.values(), key])


async def touch_versioned(
    conn: AsyncConnection, table: str, key_column: str, key: str
) -> dict[str, Any] | None:
    """Bump source_version for a change stored in a child table."""
    return await update_versioned(conn, table, key_column, key, {})
