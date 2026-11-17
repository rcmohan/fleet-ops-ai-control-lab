from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from copy import deepcopy
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from psycopg import AsyncConnection, errors as pg_errors
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from .contracts import Operation, Parameter, ServiceContract
from .db import Database, fetch_one
from .errors import DependencyRejected, DependencyUnavailable, invalid
from .handlers import Handler, HandlerRegistry, RequestContext, Worker
from .outbox import run_dispatcher
from .services import ServiceClients
from .util import content_hash

log = logging.getLogger("fleetops.worker")

_FORWARDED_PREFIX = re.compile(r"/[a-z0-9-]+")


class HealthStatus(BaseModel):
    service: str
    status: str
    version: str


class ForwardedPrefixMiddleware:
    """Honor the local gateway's X-Forwarded-Prefix so /docs works under /<service>/."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            prefix = headers.get(b"x-forwarded-prefix", b"").decode("latin-1")
            if _FORWARDED_PREFIX.fullmatch(prefix) and scope["path"].startswith(prefix + "/"):
                scope = {**scope, "root_path": scope.get("root_path", "") + prefix}
        await self.app(scope, receive, send)


def _python_type(value: Any) -> type[Any]:
    if isinstance(value, bool):
        return bool
    if isinstance(value, int):
        return int
    if isinstance(value, float):
        return float
    if isinstance(value, list):
        return list[Any]
    if isinstance(value, dict):
        return dict[str, Any]
    return str


def _model_from_example(
    name: str,
    example: dict[str, Any],
    *,
    fields_required: bool = False,
    nullable: frozenset[str] = frozenset(),
) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for key, value in example.items():
        annotation: Any = _python_type(value)
        if key in nullable or value is None:
            annotation = annotation | None
        fields[key] = (annotation, ... if fields_required else value)
    return create_model(name, __config__=ConfigDict(extra="forbid"), **fields)


def _inline_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic puts nested models under $defs; OpenAPI cannot resolve those refs inline."""
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return resolve(definitions[ref.removeprefix("#/$defs/")])
            return {key: resolve(value) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


def _replace_tokens(value: Any, request: Request) -> Any:
    if isinstance(value, dict):
        return {key: _replace_tokens(item, request) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_tokens(item, request) for item in value]
    if isinstance(value, str):
        for name, replacement in request.path_params.items():
            value = value.replace(f"{{{name}}}", replacement)
        return value
    return value


def _openapi_parameters(operation: Operation) -> list[dict[str, Any]]:
    declared = {(parameter.name, parameter.location) for parameter in operation.parameters}
    parameters = list(operation.parameters)
    for name in re.findall(r"{([^}]+)}", operation.path):
        if (name, "path") not in declared:
            parameters.append(Parameter(name=name, location="path", required=True))
    if operation.method == "POST":
        parameters.append(
            Parameter(
                name="Idempotency-Key",
                location="header",
                description="Replays the original response when the same request is retried.",
            )
        )
    return [
        {
            "name": parameter.name,
            "in": parameter.location,
            "required": parameter.required or parameter.location == "path",
            "description": parameter.description,
            "schema": {"type": parameter.schema_type},
        }
        for parameter in parameters
    ]


def _check_required_parameters(operation: Operation, request: Request) -> None:
    for parameter in operation.parameters:
        if not parameter.required:
            continue
        if parameter.location == "query" and parameter.name not in request.query_params:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required query parameter: {parameter.name}",
            )
        if parameter.location == "header" and parameter.name not in request.headers:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required header: {parameter.name}",
            )


async def _read_body(request: Request, model: type[BaseModel]) -> BaseModel:
    try:
        payload = await request.json()
    except ValueError as exc:
        raise invalid("INVALID_JSON", "request body must be JSON") from exc
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_url=False, include_context=False, include_input=False),
        ) from exc


def _stub_endpoint(operation: Operation, request_model: type[BaseModel] | None):
    async def endpoint(request: Request) -> dict[str, Any]:
        _check_required_parameters(operation, request)
        if request_model is not None:
            try:
                payload = await request.json()
                request_model.model_validate(payload)
            except Exception as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _replace_tokens(deepcopy(operation.response), request)

    endpoint.__name__ = operation.operation_id
    endpoint.__doc__ = operation.summary
    return endpoint


async def _claim_idempotency_key(
    conn: AsyncConnection, operation_id: str, key: str, request_hash: str
) -> dict[str, Any] | None:
    """Return the stored response for a replay, or None when this request owns the key."""
    if not 1 <= len(key) <= 128:
        raise invalid("INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be 1-128 characters")
    claimed = await fetch_one(
        conn,
        """
        INSERT INTO runtime.idempotency_keys (operation_id, idempotency_key, request_hash)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING idempotency_key
        """,
        (operation_id, key, request_hash),
    )
    if claimed is not None:
        return None
    existing = await fetch_one(
        conn,
        "SELECT request_hash, response FROM runtime.idempotency_keys "
        "WHERE operation_id = %s AND idempotency_key = %s",
        (operation_id, key),
    )
    assert existing is not None
    if existing["request_hash"] != request_hash:
        raise invalid(
            "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was already used for a different request"
        )
    return existing["response"]


def _real_endpoint(
    operation: Operation,
    handler: Handler,
    request_model: type[BaseModel] | None,
    database: Database | None,
    services: ServiceClients,
):
    async def endpoint(request: Request) -> dict[str, Any]:
        _check_required_parameters(operation, request)
        body = await _read_body(request, request_model) if request_model else None
        if database is None:
            return await handler.func(RequestContext(request, body, services))

        key = request.headers.get("idempotency-key") if operation.method == "POST" else None
        async with database.transaction() as conn:
            if key is not None:
                request_hash = content_hash(
                    [request.url.path, body.model_dump(mode="json") if body else None]
                )
                replay = await _claim_idempotency_key(
                    conn, operation.operation_id, key, request_hash
                )
                if replay is not None:
                    return replay
            result = await handler.func(RequestContext(request, body, services, conn))
            if key is not None:
                await conn.execute(
                    "UPDATE runtime.idempotency_keys SET response = %s "
                    "WHERE operation_id = %s AND idempotency_key = %s",
                    (Jsonb(jsonable_encoder(result)), operation.operation_id, key),
                )
            return result

    endpoint.__name__ = operation.operation_id
    endpoint.__doc__ = operation.summary
    return endpoint


def _error(status_code: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"detail": {"code": code, "message": message, **extra}}
    )


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DependencyUnavailable)
    async def dependency_unavailable(_: Request, exc: DependencyUnavailable) -> JSONResponse:
        return _error(
            503,
            "DEPENDENCY_UNAVAILABLE",
            f"{exc.service} is unavailable",
            dependency=exc.service,
            reason=exc.reason,
        )

    @app.exception_handler(DependencyRejected)
    async def dependency_rejected(_: Request, exc: DependencyRejected) -> JSONResponse:
        return _error(
            502,
            "DEPENDENCY_REJECTED",
            f"{exc.service} rejected the request",
            dependency=exc.service,
            dependencyStatus=exc.status_code,
        )

    @app.exception_handler(pg_errors.UniqueViolation)
    async def unique_violation(_: Request, exc: pg_errors.UniqueViolation) -> JSONResponse:
        return _error(409, "ALREADY_EXISTS", "a record with the same unique value exists",
                      constraint=exc.diag.constraint_name)

    @app.exception_handler(pg_errors.IntegrityError)
    async def integrity_error(_: Request, exc: pg_errors.IntegrityError) -> JSONResponse:
        return _error(422, "CONSTRAINT_VIOLATION", "the change violates a data rule",
                      constraint=exc.diag.constraint_name)


async def _run_worker(worker: Worker, database: Database, services: ServiceClients) -> None:
    while True:
        busy = False
        try:
            busy = await worker.step(database, services)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("worker %s failed", worker.name)
        if not busy:
            await asyncio.sleep(worker.interval)


def build_app(
    contract: ServiceContract,
    handlers: HandlerRegistry | None = None,
    *,
    database: Database | None = None,
    services: ServiceClients | None = None,
    run_background: bool = True,
) -> FastAPI:
    """Without handlers, every route returns its contract example (stub mode)."""
    real = handlers is not None
    if real:
        operation_ids = {operation.operation_id for operation in contract.operations}
        missing = operation_ids - handlers.handlers.keys()
        unknown = handlers.handlers.keys() - operation_ids
        if missing or unknown:
            raise ValueError(
                f"{contract.slug}: handlers missing {sorted(missing)}, unknown {sorted(unknown)}"
            )
    services = services or ServiceClients()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        tasks: list[asyncio.Task] = []
        if database is not None:
            await database.open()
            if run_background:
                tasks.append(asyncio.create_task(run_dispatcher(database, services)))
                tasks += [
                    asyncio.create_task(_run_worker(worker, database, services))
                    for worker in handlers.workers
                ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await services.aclose()
            if database is not None:
                await database.close()

    app = FastAPI(
        title=contract.title,
        description=contract.description,
        version=contract.version,
        contact={"name": "FleetOps AI Control Lab"},
        lifespan=lifespan if real else None,
    )
    app.add_middleware(ForwardedPrefixMiddleware)
    if real:
        _install_error_handlers(app)

    @app.get("/health/live", response_model=HealthStatus, tags=["Platform"])
    async def liveness() -> HealthStatus:
        return HealthStatus(service=contract.slug, status="ok", version=contract.version)

    @app.get("/health/ready", response_model=HealthStatus, tags=["Platform"])
    async def readiness() -> Any:
        if database is not None and not await database.ping():
            return JSONResponse(
                status_code=503,
                content={"service": contract.slug, "status": "database_unavailable",
                         "version": contract.version},
            )
        return HealthStatus(service=contract.slug, status="ready", version=contract.version)

    for operation in contract.operations:
        handler = handlers.handlers[operation.operation_id] if real else None
        response_model = _model_from_example(
            f"{operation.operation_id}Response",
            operation.response,
            fields_required=real,
            nullable=handler.nullable if handler else frozenset(),
        )
        if handler is not None and handler.request_model is not None:
            request_model: type[BaseModel] | None = handler.request_model
        elif operation.request is not None:
            request_model = _model_from_example(
                f"{operation.operation_id}Request", operation.request, fields_required=True
            )
        else:
            request_model = None
        openapi_extra: dict[str, Any] = {
            "parameters": _openapi_parameters(operation),
            "x-dummy-implementation": not real,
        }
        if request_model is not None:
            openapi_extra["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": _inline_schema(request_model),
                        "example": operation.request,
                    }
                },
            }
        endpoint = (
            _real_endpoint(operation, handler, request_model, database, services)
            if handler is not None
            else _stub_endpoint(operation, request_model)
        )
        app.add_api_route(
            operation.path,
            endpoint,
            methods=[operation.method],
            operation_id=operation.operation_id,
            summary=operation.summary,
            response_model=response_model,
            tags=[contract.title],
            openapi_extra=openapi_extra,
        )

    return app
