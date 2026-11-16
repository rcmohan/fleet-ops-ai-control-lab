from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, date, datetime
from typing import Any

from .errors import invalid


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return value.isoformat()


def parse_time(raw: str | None, name: str) -> datetime | None:
    if raw is None:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise invalid("INVALID_TIMESTAMP", f"{name} must be an ISO-8601 timestamp") from exc
    if value.tzinfo is None:
        raise invalid("INVALID_TIMESTAMP", f"{name} must include a UTC offset")
    return value


def content_hash(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def encode_cursor(values: list[Any]) -> str:
    raw = json.dumps(values, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None, size: int) -> list[Any] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError) as exc:
        raise invalid("INVALID_CURSOR", "cursor is not valid") from exc
    if not isinstance(values, list) or len(values) != size:
        raise invalid("INVALID_CURSOR", "cursor is not valid")
    return values


def parse_limit(raw: str | None, default: int = 50, maximum: int = 200) -> int:
    if raw is None:
        return default
    try:
        limit = int(raw)
    except ValueError as exc:
        raise invalid("INVALID_LIMIT", "limit must be an integer") from exc
    if not 1 <= limit <= maximum:
        raise invalid("INVALID_LIMIT", f"limit must be between 1 and {maximum}")
    return limit
