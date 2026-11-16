"""Typed API errors. Every error body is {"detail": {"code": ..., "message": ..., ...}}."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def api_error(status_code: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message, **extra}
    )


def not_found(entity: str, entity_id: str) -> HTTPException:
    return api_error(404, "NOT_FOUND", f"{entity} {entity_id} does not exist", entityId=entity_id)


def conflict(code: str, message: str, **extra: Any) -> HTTPException:
    return api_error(409, code, message, **extra)


def invalid(code: str, message: str, **extra: Any) -> HTTPException:
    return api_error(422, code, message, **extra)


def forbidden(code: str, message: str, **extra: Any) -> HTTPException:
    return api_error(403, code, message, **extra)


class DependencyUnavailable(Exception):
    """A downstream service timed out, refused the connection, or returned 5xx."""

    def __init__(self, service: str, reason: str) -> None:
        super().__init__(f"{service}: {reason}")
        self.service = service
        self.reason = reason


class DependencyRejected(Exception):
    """A downstream service rejected our request with a 4xx other than 404."""

    def __init__(self, service: str, status_code: int, body: Any) -> None:
        super().__init__(f"{service} returned {status_code}")
        self.service = service
        self.status_code = status_code
        self.body = body
