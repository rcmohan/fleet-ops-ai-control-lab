"""Where exports go.

FileSink mirrors the GCP layout in a local directory, so the whole flow runs (and can be
inspected) without a GCP project:

    <root>/topics/<topic>.jsonl                     one published message per line
    <root>/collections/<collection>/<id>.json       one document per file

GcpSink writes the same messages to Pub/Sub and the same documents to Firestore. Its client
libraries are imported only when it is used, so nothing else needs them installed.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

DOC_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
FIRESTORE_BATCH = 400   # Firestore allows 500 writes per batch; stay under it
PUBLISH_TIMEOUT = 30.0


class SinkUnavailable(Exception):
    """The sink could not take the write; the caller should retry later."""


class Sink(Protocol):
    kind: str

    async def publish(self, topic: str, data: dict[str, Any], *, ordering_key: str,
                      attributes: dict[str, str]) -> None: ...

    async def put(self, collection: str, documents: dict[str, dict[str, Any]]) -> None: ...

    def describe(self) -> dict[str, str]: ...


def check_id(doc_id: str) -> str:
    if not DOC_ID.match(doc_id):
        raise ValueError(f"unsafe document id {doc_id!r}")
    return doc_id


def encode(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


class FileSink:
    kind = "file"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def describe(self) -> dict[str, str]:
        return {"kind": self.kind, "root": str(self.root)}

    async def publish(self, topic: str, data: dict[str, Any], *, ordering_key: str,
                      attributes: dict[str, str]) -> None:
        line = {"publishedAt": datetime.now(UTC).isoformat(), "orderingKey": ordering_key,
                "attributes": attributes, "data": data}
        path = self.root / "topics" / f"{check_id(topic)}.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("ab") as handle:
                handle.write(encode(line) + b"\n")
        except OSError as exc:
            raise SinkUnavailable(f"cannot write {path}: {exc}") from exc

    async def put(self, collection: str, documents: dict[str, dict[str, Any]]) -> None:
        folder = self.root / "collections" / check_id(collection)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for doc_id, document in documents.items():
                target = folder / f"{check_id(doc_id)}.json"
                temporary = target.with_suffix(".json.tmp")
                temporary.write_bytes(json.dumps(document, indent=2, sort_keys=True).encode())
                os.replace(temporary, target)  # readers never see a half-written document
        except OSError as exc:
            raise SinkUnavailable(f"cannot write {folder}: {exc}") from exc


class GcpSink:
    """Pub/Sub with per-key ordering, and Firestore batched writes. Credentials come from
    Application Default Credentials (GOOGLE_APPLICATION_CREDENTIALS or the metadata server)."""

    kind = "gcp"

    def __init__(self, project: str, *, database: str = "(default)",
                 publisher: Any = None, firestore_client: Any = None) -> None:
        if not project:
            raise ValueError("FLEETOPS_GCP_PROJECT is required for the gcp sink")
        if publisher is None:
            from google.cloud import pubsub_v1

            publisher = pubsub_v1.PublisherClient(
                publisher_options=pubsub_v1.types.PublisherOptions(enable_message_ordering=True))
        if firestore_client is None:
            from google.cloud import firestore

            firestore_client = firestore.Client(project=project, database=database)
        self.project, self.database = project, database
        self.publisher, self.firestore = publisher, firestore_client

    def describe(self) -> dict[str, str]:
        return {"kind": self.kind, "project": self.project, "database": self.database}

    def _publish(self, topic: str, data: dict[str, Any], ordering_key: str,
                 attributes: dict[str, str]) -> None:
        topic_path = f"projects/{self.project}/topics/{topic}"
        try:
            future = self.publisher.publish(topic_path, encode(data),
                                            ordering_key=ordering_key, **attributes)
            future.result(timeout=PUBLISH_TIMEOUT)
        except Exception as exc:
            # A failed publish pauses its ordering key; resume it so the retry can go out.
            self.publisher.resume_publish(topic_path, ordering_key)
            raise SinkUnavailable(f"publish to {topic} failed: {exc}") from exc

    def _put(self, collection: str, documents: dict[str, dict[str, Any]]) -> None:
        items = [(check_id(doc_id), doc) for doc_id, doc in documents.items()]
        try:
            for start in range(0, len(items), FIRESTORE_BATCH):
                batch = self.firestore.batch()
                for doc_id, document in items[start:start + FIRESTORE_BATCH]:
                    batch.set(self.firestore.collection(collection).document(doc_id), document)
                batch.commit()
        except Exception as exc:
            raise SinkUnavailable(f"write to {collection} failed: {exc}") from exc

    async def publish(self, topic: str, data: dict[str, Any], *, ordering_key: str,
                      attributes: dict[str, str]) -> None:
        await asyncio.to_thread(self._publish, topic, data, ordering_key, attributes)

    async def put(self, collection: str, documents: dict[str, dict[str, Any]]) -> None:
        if documents:
            await asyncio.to_thread(self._put, collection, documents)


def sink_from_env() -> Sink:
    kind = os.environ.get("FLEETOPS_EXPORT_SINK", "file")
    if kind == "file":
        return FileSink(os.environ.get("FLEETOPS_EXPORT_DIR", ".cloud-export"))
    if kind == "gcp":
        return GcpSink(os.environ.get("FLEETOPS_GCP_PROJECT", ""),
                       database=os.environ.get("FLEETOPS_FIRESTORE_DATABASE", "(default)"))
    raise ValueError(f"FLEETOPS_EXPORT_SINK must be 'file' or 'gcp', not {kind!r}")
