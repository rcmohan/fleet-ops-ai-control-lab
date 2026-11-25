"""Where exports go.

Two kinds of output: rows appended to tables (events, incidents, evidence, context; see
tables.py), and messages published to a topic (incident changes, which will wake the cloud
agent once it exists).

FileSink mirrors that layout in a local directory, so the whole flow runs (and can be
inspected) without a GCP project:

    <root>/tables/<table>.jsonl      one appended row per line
    <root>/topics/<topic>.jsonl      one published message per line

GcpSink buffers rows in memory and loads them into BigQuery with batch load jobs on each
flush (load jobs are free; streaming inserts are not), and publishes to Pub/Sub. Rows still
buffered when the exporter stops are lost, which is acceptable here: the local stack stays the
system of record and BigQuery is a copy for analysis. Its client libraries are imported only
when used, so nothing else needs them installed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .tables import DAY_MS, TABLES, Table

log = logging.getLogger("fleetops.cloud_exporter")

NAME = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
PUBLISH_TIMEOUT = 30.0
LOAD_TIMEOUT = 300.0
MAX_BUFFERED_ROWS = 200_000   # per table; past this the oldest rows are dropped


class SinkUnavailable(Exception):
    """The sink could not take the write; the caller should retry later."""


class Sink(Protocol):
    kind: str

    async def publish(self, topic: str, data: dict[str, Any], *, ordering_key: str,
                      attributes: dict[str, str]) -> None: ...

    async def append(self, table: str, rows: list[dict[str, Any]]) -> None: ...

    async def flush(self) -> dict[str, Any]: ...

    def describe(self) -> dict[str, Any]: ...


def check_name(name: str) -> str:
    if not NAME.match(name):
        raise ValueError(f"unsafe name {name!r}")
    return name


def check_table(name: str) -> Table:
    if name not in TABLES:
        raise ValueError(f"unknown table {name!r}")
    return TABLES[name]


def encode(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


class FileSink:
    kind = "file"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "root": str(self.root)}

    def _append_lines(self, path: Path, lines: list[Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("ab") as handle:
                handle.write(b"".join(encode(line) + b"\n" for line in lines))
        except OSError as exc:
            raise SinkUnavailable(f"cannot write {path}: {exc}") from exc

    async def publish(self, topic: str, data: dict[str, Any], *, ordering_key: str,
                      attributes: dict[str, str]) -> None:
        line = {"publishedAt": datetime.now(UTC).isoformat(), "orderingKey": ordering_key,
                "attributes": attributes, "data": data}
        self._append_lines(self.root / "topics" / f"{check_name(topic)}.jsonl", [line])

    async def append(self, table: str, rows: list[dict[str, Any]]) -> None:
        check_table(table)
        if rows:
            self._append_lines(self.root / "tables" / f"{table}.jsonl", rows)

    async def flush(self) -> dict[str, Any]:
        return {"loaded": {}, "failed": {}}   # rows are already on disk


class BigQueryWriter:
    """The two BigQuery calls GcpSink makes, kept apart so tests can replace them."""

    def __init__(self, project: str, dataset: str, location: str) -> None:
        from google.cloud import bigquery

        self.bigquery, self.dataset, self.location = bigquery, f"{project}.{dataset}", location
        self.client = bigquery.Client(project=project, location=location)

    def create(self, table: Table) -> None:
        bq = self.bigquery
        target = bq.Table(f"{self.dataset}.{table.name}",
                          schema=[bq.SchemaField(name, kind) for name, kind in table.columns])
        target.time_partitioning = bq.TimePartitioning(
            type_=bq.TimePartitioningType.DAY, field=table.partition_by,
            expiration_ms=table.expire_days * DAY_MS if table.expire_days else None)
        target.clustering_fields = list(table.cluster_by)
        self.client.create_table(target, exists_ok=True)
        view = bq.Table(f"{self.dataset}.{table.view}")
        view.view_query = table.view_sql(self.dataset)
        self.client.create_table(view, exists_ok=True)

    def load(self, table: Table, rows: list[dict[str, Any]]) -> None:
        bq = self.bigquery
        config = bq.LoadJobConfig(
            schema=[bq.SchemaField(name, kind) for name, kind in table.columns],
            write_disposition=bq.WriteDisposition.WRITE_APPEND)
        job = self.client.load_table_from_json(rows, f"{self.dataset}.{table.name}",
                                               job_config=config, location=self.location)
        job.result(timeout=LOAD_TIMEOUT)


class GcpSink:
    """BigQuery batch loads on flush, and Pub/Sub with per-key ordering. Credentials come from
    Application Default Credentials (GOOGLE_APPLICATION_CREDENTIALS or the metadata server)."""

    kind = "gcp"

    def __init__(self, project: str, *, dataset: str = "fleetops", location: str = "US",
                 writer: Any = None, publisher: Any = None) -> None:
        if not project:
            raise ValueError("FLEETOPS_GCP_PROJECT is required for the gcp sink")
        check_name(dataset)
        self.project, self.dataset, self.location = project, dataset, location
        self.writer = writer or BigQueryWriter(project, dataset, location)
        self._publisher = publisher
        self._buffers: dict[str, list[dict[str, Any]]] = {}
        self._created: set[str] = set()
        self._flush_lock = asyncio.Lock()
        self.dropped = 0

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "project": self.project, "dataset": self.dataset,
                "location": self.location,
                "bufferedRows": {name: len(rows) for name, rows in self._buffers.items() if rows},
                "droppedRows": self.dropped}

    def _buffer(self, table: str, rows: list[dict[str, Any]], *, front: bool = False) -> None:
        buffer = self._buffers.setdefault(table, [])
        if front:
            buffer[:0] = rows
        else:
            buffer.extend(rows)
        if len(buffer) > MAX_BUFFERED_ROWS:   # BigQuery has been unreachable for a long time
            excess = len(buffer) - MAX_BUFFERED_ROWS
            del buffer[:excess]
            self.dropped += excess

    async def append(self, table: str, rows: list[dict[str, Any]]) -> None:
        check_table(table)
        self._buffer(table, list(rows))

    def _load(self, table: Table, rows: list[dict[str, Any]]) -> None:
        if table.name not in self._created:
            self.writer.create(table)
            self._created.add(table.name)
        self.writer.load(table, rows)

    async def flush(self) -> dict[str, Any]:
        """Load every buffered row. A table whose load fails keeps its rows for the next flush."""
        async with self._flush_lock:
            loaded: dict[str, int] = {}
            failed: dict[str, str] = {}
            for name in list(self._buffers):
                rows, self._buffers[name] = self._buffers[name], []
                if not rows:
                    continue
                try:
                    await asyncio.to_thread(self._load, TABLES[name], rows)
                except Exception as exc:
                    log.warning("loading %d rows into %s failed: %s", len(rows), name, exc)
                    self._buffer(name, rows, front=True)
                    failed[name] = str(exc)
                else:
                    loaded[name] = len(rows)
            return {"loaded": loaded, "failed": failed}

    @property
    def publisher(self) -> Any:
        if self._publisher is None:
            from google.cloud import pubsub_v1

            self._publisher = pubsub_v1.PublisherClient(
                publisher_options=pubsub_v1.types.PublisherOptions(enable_message_ordering=True))
        return self._publisher

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

    async def publish(self, topic: str, data: dict[str, Any], *, ordering_key: str,
                      attributes: dict[str, str]) -> None:
        await asyncio.to_thread(self._publish, check_name(topic), data, ordering_key, attributes)


def sink_from_env() -> Sink:
    kind = os.environ.get("FLEETOPS_EXPORT_SINK", "file")
    if kind == "file":
        return FileSink(os.environ.get("FLEETOPS_EXPORT_DIR", ".cloud-export"))
    if kind == "gcp":
        return GcpSink(os.environ.get("FLEETOPS_GCP_PROJECT", ""),
                       dataset=os.environ.get("FLEETOPS_BIGQUERY_DATASET", "fleetops"),
                       location=os.environ.get("FLEETOPS_BIGQUERY_LOCATION", "US"))
    raise ValueError(f"FLEETOPS_EXPORT_SINK must be 'file' or 'gcp', not {kind!r}")
