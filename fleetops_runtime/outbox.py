"""Transactional outbox: a message is written in the same transaction as the business change
and delivered to another service afterwards, with retries, so neither is lost if the other fails."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from .db import Database, fetch_all
from .errors import DependencyRejected, DependencyUnavailable
from .services import ServiceClients

log = logging.getLogger("fleetops.outbox")

MAX_ATTEMPTS = 20


async def enqueue(conn: AsyncConnection, destination: str, path: str, payload: Any) -> None:
    await conn.execute(
        "INSERT INTO runtime.outbox (destination, path, payload) VALUES (%s, %s, %s)",
        (destination, path, Jsonb(payload)),
    )


async def dispatch_once(db: Database, services: ServiceClients, batch: int = 20) -> int:
    """Deliver due messages. Returns how many were delivered."""
    delivered = 0
    async with db.transaction() as conn:
        rows = await fetch_all(
            conn,
            """
            SELECT message_id, destination, path, payload, attempts
            FROM runtime.outbox
            WHERE status = 'pending' AND next_attempt_at <= now()
            ORDER BY message_id
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            (batch,),
        )
        for row in rows:
            try:
                await services.post(row["destination"], row["path"], row["payload"])
            except DependencyUnavailable as exc:
                attempts = row["attempts"] + 1
                status = "dead" if attempts >= MAX_ATTEMPTS else "pending"
                await conn.execute(
                    """
                    UPDATE runtime.outbox
                    SET attempts = %s, status = %s, last_error = %s,
                        next_attempt_at = now() + make_interval(secs => %s)
                    WHERE message_id = %s
                    """,
                    (attempts, status, str(exc), min(2**attempts, 300), row["message_id"]),
                )
                continue
            except DependencyRejected as exc:
                # The receiver refused the message; retrying the same payload cannot succeed.
                await conn.execute(
                    "UPDATE runtime.outbox SET status = 'dead', attempts = attempts + 1, "
                    "last_error = %s WHERE message_id = %s",
                    (f"HTTP {exc.status_code}: {exc.body}", row["message_id"]),
                )
                log.error("outbox message %s rejected by %s", row["message_id"], exc.service)
                continue
            await conn.execute(
                "UPDATE runtime.outbox SET status = 'delivered', attempts = attempts + 1, "
                "delivered_at = now(), last_error = NULL WHERE message_id = %s",
                (row["message_id"],),
            )
            delivered += 1
    return delivered


async def run_dispatcher(
    db: Database, services: ServiceClients, interval: float = 0.5, batch: int = 100
) -> None:
    while True:
        delivered = 0
        try:
            delivered = await dispatch_once(db, services, batch)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("outbox dispatch failed")
        if delivered < batch:  # caught up (or failing); otherwise drain the backlog at once
            await asyncio.sleep(interval)
