from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Annotated, Any, Callable, Protocol
from uuid import NAMESPACE_URL, uuid5

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict


def require_tenant(
    tenant_id: Annotated[
        str,
        Header(
            alias="X-Tenant-ID",
            min_length=3,
            max_length=64,
            description="Opaque Tenant Master identifier",
        ),
    ],
) -> str:
    tenant_master_url = os.getenv("TENANT_MASTER_URL")
    if not tenant_master_url:
        return tenant_id
    request = urllib.request.Request(
        f"{tenant_master_url.rstrip('/')}/v1/tenants/{tenant_id}",
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            tenant = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(403, "Unknown tenant") from exc
        raise HTTPException(503, "Tenant Master is unavailable") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(503, "Tenant Master is unavailable") from exc
    if tenant.get("lifecycleStatus") != "active":
        raise HTTPException(403, "Tenant is not active")
    return tenant_id


TenantId = Annotated[
    str,
    Depends(require_tenant),
]


class ApiModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        protected_namespaces=(),
    )


class DocumentStore(Protocol):
    def get(self, tenant_id: str, record_id: str) -> dict[str, Any]: ...
    def list(self, tenant_id: str) -> list[dict[str, Any]]: ...
    def create(
        self,
        tenant_id: str,
        prefix: str,
        id_field: str,
        body: dict[str, Any],
        unique_field: str | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]: ...
    def mutate(
        self,
        tenant_id: str,
        record_id: str,
        operation: str,
        idempotency_key: str | None,
        change: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]: ...


def _record_id(
    prefix: str,
    tenant_id: str,
    body: dict[str, Any],
    unique_field: str | None,
    idempotency_key: str | None,
) -> str:
    stable_value = body.get(unique_field) if unique_field else idempotency_key
    if not stable_value:
        stable_value = json.dumps(body, sort_keys=True, separators=(",", ":"))
    value = uuid5(NAMESPACE_URL, f"fleetops:{prefix}:{tenant_id}:{stable_value}")
    return f"{prefix}_{value.hex[:16]}"


class InMemoryDocumentStore:
    """Fast tenant-scoped adapter used by tests and local non-Compose runs."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, dict[str, Any]]] = {}
        self._idempotent_results: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._lock = RLock()

    def get(self, tenant_id: str, record_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                return deepcopy(self._records[tenant_id][record_id])
            except KeyError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=f"Master-data record '{record_id}' was not found",
                ) from exc

    def list(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(self._records.get(tenant_id, {}).values()))

    def create(
        self,
        tenant_id: str,
        prefix: str,
        id_field: str,
        body: dict[str, Any],
        unique_field: str | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        with self._lock:
            replay_key = (
                (tenant_id, "create", idempotency_key) if idempotency_key else None
            )
            if replay_key and replay_key in self._idempotent_results:
                return deepcopy(self._idempotent_results[replay_key])
            tenant_records = self._records.setdefault(tenant_id, {})
            if unique_field and any(
                item.get(unique_field) == body.get(unique_field)
                for item in tenant_records.values()
            ):
                raise HTTPException(409, f"{unique_field} already exists")
            record_id = _record_id(
                prefix, tenant_id, body, unique_field, idempotency_key
            )
            record = {
                **body,
                "tenantId": tenant_id,
                id_field: record_id,
                "sourceVersion": 1,
            }
            tenant_records[record_id] = record
            if replay_key:
                self._idempotent_results[replay_key] = deepcopy(record)
            return deepcopy(record)

    def mutate(
        self,
        tenant_id: str,
        record_id: str,
        operation: str,
        idempotency_key: str | None,
        change: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        with self._lock:
            replay_key = (
                (tenant_id, operation, idempotency_key) if idempotency_key else None
            )
            if replay_key and replay_key in self._idempotent_results:
                return deepcopy(self._idempotent_results[replay_key])
            record = self.get(tenant_id, record_id)
            change(record)
            record["sourceVersion"] += 1
            self._records[tenant_id][record_id] = record
            if replay_key:
                self._idempotent_results[replay_key] = deepcopy(record)
            return deepcopy(record)


class PostgresDocumentStore:
    """Durable tenant-scoped JSON document repository in a service-owned DB."""

    def __init__(self, database_url: str, migrations: Path) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL mode requires psycopg; install requirements.txt"
            ) from exc
        self._psycopg = psycopg
        self._dict_row = dict_row
        self._database_url = database_url
        self._apply_migrations(migrations)

    def _connect(self):
        return self._psycopg.connect(
            self._database_url,
            row_factory=self._dict_row,
        )

    def _apply_migrations(self, migrations: Path) -> None:
        with self._connect() as connection:
            connection.execute("CREATE SCHEMA IF NOT EXISTS platform")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS platform.schema_migrations (
                    migration_name text PRIMARY KEY,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            applied = {
                row["migration_name"]
                for row in connection.execute(
                    "SELECT migration_name FROM platform.schema_migrations"
                ).fetchall()
            }
            for migration in sorted(migrations.glob("*.sql")):
                if migration.name in applied:
                    continue
                connection.execute(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO platform.schema_migrations (migration_name) VALUES (%s)",
                    (migration.name,),
                )

    def get(self, tenant_id: str, record_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT document FROM master_data.records
                WHERE tenant_id = %s AND record_id = %s
                """,
                (tenant_id, record_id),
            ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Master-data record '{record_id}' was not found",
            )
        return deepcopy(row["document"])

    def list(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT document FROM master_data.records
                WHERE tenant_id = %s ORDER BY record_id
                """,
                (tenant_id,),
            ).fetchall()
        return [deepcopy(row["document"]) for row in rows]

    def create(
        self,
        tenant_id: str,
        prefix: str,
        id_field: str,
        body: dict[str, Any],
        unique_field: str | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        replay = self._replay(tenant_id, "create", idempotency_key)
        if replay is not None:
            return replay
        record_id = _record_id(prefix, tenant_id, body, unique_field, idempotency_key)
        record = {
            **body,
            "tenantId": tenant_id,
            id_field: record_id,
            "sourceVersion": 1,
        }
        natural_key = str(body[unique_field]) if unique_field else None
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO master_data.records
                        (tenant_id, record_id, natural_key, document, source_version)
                    VALUES (%s, %s, %s, %s::jsonb, 1)
                    """,
                    (tenant_id, record_id, natural_key, json.dumps(record)),
                )
                self._remember(connection, tenant_id, "create", idempotency_key, record)
        except self._psycopg.errors.UniqueViolation as exc:
            raise HTTPException(
                409, f"{unique_field or id_field} already exists"
            ) from exc
        return record

    def mutate(
        self,
        tenant_id: str,
        record_id: str,
        operation: str,
        idempotency_key: str | None,
        change: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        replay = self._replay(tenant_id, operation, idempotency_key)
        if replay is not None:
            return replay
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT document FROM master_data.records
                WHERE tenant_id = %s AND record_id = %s FOR UPDATE
                """,
                (tenant_id, record_id),
            ).fetchone()
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Master-data record '{record_id}' was not found",
                )
            record = deepcopy(row["document"])
            change(record)
            record["sourceVersion"] += 1
            connection.execute(
                """
                UPDATE master_data.records
                SET document = %s::jsonb,
                    source_version = %s,
                    updated_at = now()
                WHERE tenant_id = %s AND record_id = %s
                """,
                (
                    json.dumps(record),
                    record["sourceVersion"],
                    tenant_id,
                    record_id,
                ),
            )
            self._remember(connection, tenant_id, operation, idempotency_key, record)
        return record

    def _replay(
        self, tenant_id: str, operation: str, idempotency_key: str | None
    ) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT response FROM master_data.idempotency_results
                WHERE tenant_id = %s AND operation = %s AND idempotency_key = %s
                """,
                (tenant_id, operation, idempotency_key),
            ).fetchone()
        return deepcopy(row["response"]) if row else None

    @staticmethod
    def _remember(
        connection: Any,
        tenant_id: str,
        operation: str,
        idempotency_key: str | None,
        response: dict[str, Any],
    ) -> None:
        if idempotency_key:
            connection.execute(
                """
                INSERT INTO master_data.idempotency_results
                    (tenant_id, operation, idempotency_key, response)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (tenant_id, operation, idempotency_key, json.dumps(response)),
            )


def create_document_store(service_directory: Path) -> DocumentStore:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return PostgresDocumentStore(
            database_url,
            service_directory / "migrations",
        )
    return InMemoryDocumentStore()


def dump_model(model: ApiModel, *, exclude_unset: bool = False) -> dict[str, Any]:
    return model.model_dump(
        by_alias=True,
        exclude_unset=exclude_unset,
        mode="json",
    )


def normalize_codes(values: list[str], field: str) -> list[str]:
    normalized = list(
        dict.fromkeys(value.strip().lower() for value in values if value.strip())
    )
    if len(normalized) != len(values):
        raise HTTPException(
            status_code=422,
            detail=f"{field} must contain unique, non-empty values",
        )
    return normalized


def paged(
    records: list[dict[str, Any]],
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    try:
        offset = int(cursor or "0")
    except ValueError as exc:
        raise HTTPException(422, "cursor must be a non-negative integer") from exc
    if offset < 0:
        raise HTTPException(422, "cursor must be a non-negative integer")
    page = records[offset : offset + limit]
    next_offset = offset + len(page)
    return {
        "items": deepcopy(page),
        "nextCursor": str(next_offset) if next_offset < len(records) else "",
    }


def create_service_app(
    *, slug: str, title: str, description: str, version: str = "1.0.0"
) -> FastAPI:
    app = FastAPI(
        title=title,
        description=description,
        version=version,
        contact={"name": "FleetOps AI Control Lab"},
    )

    @app.get("/health/live", tags=["Platform"])
    def liveness() -> dict[str, str]:
        return {"service": slug, "status": "ok", "version": version}

    @app.get("/health/ready", tags=["Platform"])
    def readiness() -> dict[str, str]:
        return {"service": slug, "status": "ready", "version": version}

    return app
