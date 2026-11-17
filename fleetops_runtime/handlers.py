"""Binds real implementations to contract operations.

A service's handlers.py creates a HandlerRegistry named HANDLERS and decorates one async
function per operation_id in its contract. The contract still owns the route, method, and
example; the handler owns behavior and, where needed, an explicit request model.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict

from .services import ServiceClients
from .util import decode_cursor, parse_limit


class RequestModel(BaseModel):
    """Base for request bodies: unknown fields are rejected, strings are trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


@dataclass
class RequestContext:
    request: Request
    body: Any
    services: ServiceClients
    conn: AsyncConnection | None = None

    @property
    def path(self) -> dict[str, str]:
        return self.request.path_params

    def query(self, name: str) -> str | None:
        return self.request.query_params.get(name)

    def header(self, name: str) -> str | None:
        return self.request.headers.get(name)

    @property
    def db(self) -> AsyncConnection:
        if self.conn is None:
            raise RuntimeError("this service has no database")
        return self.conn

    def page(self, cursor_size: int, default: int = 50) -> tuple[list[Any] | None, int]:
        return decode_cursor(self.query("cursor"), cursor_size), parse_limit(
            self.query("limit"), default
        )


HandlerFunc = Callable[[RequestContext], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Handler:
    func: HandlerFunc
    request_model: type[BaseModel] | None = None
    nullable: frozenset[str] = field(default_factory=frozenset)


WorkerStep = Callable[[Any, ServiceClients], Awaitable[bool]]


@dataclass(frozen=True)
class Worker:
    """A background step the service runs repeatedly: step(database, services) -> busy.
    When it returns False (nothing more to do now), the loop sleeps for `interval` seconds."""

    name: str
    step: WorkerStep
    interval: float


class HandlerRegistry:
    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {}
        self.workers: list[Worker] = []

    def worker(self, interval: float = 1.0) -> Callable[[WorkerStep], WorkerStep]:
        def register(step: WorkerStep) -> WorkerStep:
            self.workers.append(Worker(step.__name__, step, interval))
            return step

        return register

    def operation(
        self,
        operation_id: str,
        *,
        request: type[BaseModel] | None = None,
        nullable: Iterable[str] = (),
    ) -> Callable[[HandlerFunc], HandlerFunc]:
        def register(func: HandlerFunc) -> HandlerFunc:
            if operation_id in self.handlers:
                raise ValueError(f"duplicate handler for {operation_id}")
            self.handlers[operation_id] = Handler(func, request, frozenset(nullable))
            return func

        return register
