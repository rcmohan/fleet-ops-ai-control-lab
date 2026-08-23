from dataclasses import dataclass, field
from typing import Any, Literal


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
ParameterLocation = Literal["path", "query", "header"]


@dataclass(frozen=True)
class Parameter:
    name: str
    location: ParameterLocation = "query"
    required: bool = False
    description: str = ""
    schema_type: str = "string"


@dataclass(frozen=True)
class Operation:
    method: HttpMethod
    path: str
    operation_id: str
    summary: str
    response: dict[str, Any]
    request: dict[str, Any] | None = None
    parameters: tuple[Parameter, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ServiceContract:
    slug: str
    title: str
    description: str
    operations: tuple[Operation, ...]
    version: str = "0.1.0"

