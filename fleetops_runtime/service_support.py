from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        protected_namespaces=(),
    )


class MasterDataStore:
    """Thread-safe process-local repository for synthetic service data."""

    def __init__(self, seed: dict[str, dict[str, Any]]) -> None:
        self._records = deepcopy(seed)
        self._idempotent_results: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = RLock()

    def get(self, record_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                return deepcopy(self._records[record_id])
            except KeyError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=f"Master-data record '{record_id}' was not found",
                ) from exc

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(self._records.values()))

    def create(
        self,
        prefix: str,
        id_field: str,
        body: dict[str, Any],
        unique_field: str | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        with self._lock:
            replay_key = ("create", idempotency_key) if idempotency_key else None
            if replay_key and replay_key in self._idempotent_results:
                return deepcopy(self._idempotent_results[replay_key])
            if unique_field and any(
                item.get(unique_field) == body.get(unique_field)
                for item in self._records.values()
            ):
                raise HTTPException(409, f"{unique_field} already exists")

            record_id = f"{prefix}_{uuid4().hex[:12]}"
            record = {**body, id_field: record_id, "sourceVersion": 1}
            self._records[record_id] = record
            if replay_key:
                self._idempotent_results[replay_key] = deepcopy(record)
            return deepcopy(record)

    def mutate(
        self,
        record_id: str,
        operation: str,
        idempotency_key: str | None,
        change: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        with self._lock:
            replay_key = (operation, idempotency_key) if idempotency_key else None
            if replay_key and replay_key in self._idempotent_results:
                return deepcopy(self._idempotent_results[replay_key])
            record = self.get(record_id)
            change(record)
            record["sourceVersion"] += 1
            self._records[record_id] = record
            if replay_key:
                self._idempotent_results[replay_key] = deepcopy(record)
            return deepcopy(record)


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
