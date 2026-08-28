from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, create_model

from .contracts import Operation, Parameter, ServiceContract


class HealthStatus(BaseModel):
    service: str
    status: str
    version: str


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
    name: str, example: dict[str, Any], *, fields_required: bool = False
) -> type[BaseModel]:
    fields = {
        key: (_python_type(value), ... if fields_required else value)
        for key, value in example.items()
    }
    return create_model(name, __config__=ConfigDict(extra="forbid"), **fields)


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


def _endpoint_for(operation: Operation, request_model: type[BaseModel] | None):
    async def endpoint(request: Request) -> dict[str, Any]:
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


def build_app(contract: ServiceContract) -> FastAPI:
    app = FastAPI(
        title=contract.title,
        description=contract.description,
        version=contract.version,
        contact={"name": "FleetOps AI Control Lab"},
    )

    @app.get("/health/live", response_model=HealthStatus, tags=["Platform"])
    async def liveness() -> HealthStatus:
        return HealthStatus(service=contract.slug, status="ok", version=contract.version)

    @app.get("/health/ready", response_model=HealthStatus, tags=["Platform"])
    async def readiness() -> HealthStatus:
        return HealthStatus(service=contract.slug, status="ready", version=contract.version)

    for operation in contract.operations:
        response_model = _model_from_example(
            f"{operation.operation_id}Response", operation.response
        )
        request_model = (
            _model_from_example(
                f"{operation.operation_id}Request",
                operation.request,
                fields_required=True,
            )
            if operation.request is not None
            else None
        )
        openapi_extra: dict[str, Any] = {
            "parameters": _openapi_parameters(operation),
            "x-dummy-implementation": True,
        }
        if request_model is not None:
            openapi_extra["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": request_model.model_json_schema(),
                        "example": operation.request,
                    }
                },
            }
        app.add_api_route(
            operation.path,
            _endpoint_for(operation, request_model),
            methods=[operation.method],
            operation_id=operation.operation_id,
            summary=operation.summary,
            response_model=response_model,
            tags=[contract.title],
            openapi_extra=openapi_extra,
        )

    return app
