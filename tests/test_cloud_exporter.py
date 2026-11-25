"""Cloud exporter: sinks, incident snapshots, events, context sync, and the outbox-facing errors."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from cloud_exporter.app import build_app
from cloud_exporter.exporter import SCHEMA, Exporter
from cloud_exporter.sinks import FileSink, GcpSink, SinkUnavailable
from cloud_exporter.tables import TABLES
from fleetops_runtime.services import ServiceClients

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
STAMP = "2026-11-18T09:00:00Z"
CHANGE = {"incidentId": "inc_1", "step": "scored", "stepId": 7, "at": "2026-11-18T08:59:00Z"}


def event(n: int) -> dict:
    return {"eventId": f"evt_{n}", "vehicleId": "veh_1", "eventType": "heartbeat",
            "severity": "info", "regionCode": "us-east", "observedAt": STAMP,
            "receivedAt": STAMP, "payload": {}, "synthetic": True}


class Services:
    """Fake signal-correlation, telematics-event, fleet-master, vehicle-master and twin."""

    def __init__(self) -> None:
        self.incidents = {"inc_1": {"incidentId": "inc_1", "vehicleId": "veh_1",
                                    "ruleId": "battery-connectivity-v1",
                                    "status": "case_opened", "sourceVersion": 4,
                                    "riskLevel": "high", "riskScore": 68.5,
                                    "events": [], "timeline": []}}
        self.vehicles = [{"vehicleId": f"veh_{n}", "fleetId": "flt_1"} for n in range(5)]
        self.events = [event(n) for n in range(5)]
        self.feed_queries: list[dict] = []
        self.down: set[str] = set()

    def feed(self, params) -> httpx.Response:
        self.feed_queries.append(dict(params))
        start = int(params.get("cursor") or 0)
        end = min(start + int(params["limit"]), len(self.events), start + 3)   # small pages
        return httpx.Response(200, json={"items": self.events[start:end],
                                         "nextCursor": str(end), "more": end < len(self.events)})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host in self.down:
            raise httpx.ConnectError("refused", request=request)
        if path.startswith("/v1/correlation/incidents/"):
            incident = self.incidents.get(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=incident) if incident else httpx.Response(404)
        if path == "/v1/event-feed":
            return self.feed(request.url.params)
        items = {"/v1/fleets": [{"fleetId": "flt_1"}], "/v1/vehicles": self.vehicles,
                 "/v1/digital-twins/vehicles": []}[path]
        start = int(request.url.params.get("cursor") or 0)
        page = items[start:start + 2]   # small pages, to exercise the cursor
        more = start + 2 < len(items)
        return httpx.Response(200, json={"items": page,
                                         "nextCursor": str(start + 2) if more else None})


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def exporter_for(sink, services: Services, clock=lambda: NOW, **options) -> Exporter:
    clients = ServiceClients(transport=httpx.MockTransport(services))
    return Exporter(sink, clients, context_interval=0, events_interval=0, flush_interval=0,
                    clock=clock, **options)


def topic_lines(root) -> list[dict]:
    path = root / "topics" / "fleetops-incidents.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def rows(root, table: str) -> list[dict]:
    path = root / "tables" / f"{table}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.anyio
async def test_incident_change_appends_snapshot_and_publishes(tmp_path) -> None:
    exporter = exporter_for(FileSink(tmp_path), Services())
    await exporter.export_incident_change(CHANGE)
    await exporter.export_incident_change(CHANGE)   # a redelivery is harmless

    first_row, second_row = rows(tmp_path, "incidents")
    assert {k: first_row[k] for k in ("incidentId", "status", "step", "stepId",
                                      "sourceVersion", "riskScore", "exportedAt")} == {
        "incidentId": "inc_1", "status": "case_opened", "step": "scored", "stepId": 7,
        "sourceVersion": 4, "riskScore": 68.5, "exportedAt": STAMP}
    assert first_row["incident"]["ruleId"] == "battery-connectivity-v1"
    assert set(first_row) == {name for name, _ in TABLES["incidents"].columns}
    assert rows(tmp_path, "evidence") == []   # "scored" brings no new facts

    first, second = topic_lines(tmp_path)
    assert first["orderingKey"] == "inc_1"
    assert first["attributes"] == {"incidentId": "inc_1", "vehicleId": "veh_1",
                                   "step": "scored", "status": "case_opened",
                                   "sourceVersion": "4", "dedupeKey": "inc_1:7",
                                   "hasEvidence": "false"}
    assert first["data"]["schema"] == SCHEMA and first["data"]["change"] == CHANGE
    assert first["data"]["incident"]["status"] == "case_opened"
    assert first["data"]["evidence"] is None
    assert second["attributes"]["dedupeKey"] == first["attributes"]["dedupeKey"]
    assert exporter.status()["incidentsExported"] == 2


@pytest.mark.anyio
async def test_without_a_topic_nothing_is_published(tmp_path) -> None:
    exporter = exporter_for(FileSink(tmp_path), Services(), topic="")
    await exporter.export_incident_change(CHANGE)
    assert len(rows(tmp_path, "incidents")) == 1
    assert not (tmp_path / "topics").exists()
    assert exporter.status()["topic"] is None


@pytest.mark.anyio
async def test_events_follow_the_feed_from_where_they_stopped(tmp_path) -> None:
    services = Services()
    exporter = exporter_for(FileSink(tmp_path), services)
    first = await exporter.export_events()
    assert first["appended"] == 5
    # It starts a few minutes back, then follows the cursor across pages.
    assert services.feed_queries[0] == {"limit": "200", "since": "2026-11-18T08:50:00Z"}
    assert [q.get("cursor") for q in services.feed_queries] == [None, "3"]
    stored = rows(tmp_path, "events")
    assert [r["eventId"] for r in stored] == [f"evt_{n}" for n in range(5)]
    assert set(stored[0]) == {name for name, _ in TABLES["events"].columns}

    services.events.append(event(5))
    assert (await exporter.export_events())["appended"] == 1
    assert services.feed_queries[-1]["cursor"] == "5"
    assert exporter.status()["eventsExported"] == 6


@pytest.mark.anyio
async def test_failed_event_append_is_read_again(tmp_path) -> None:
    class Flaky(FileSink):
        fail = True

        async def append(self, table, rows):
            if self.fail and table == "events":
                raise SinkUnavailable("down")
            await super().append(table, rows)

    sink, services = Flaky(tmp_path), Services()
    exporter = exporter_for(sink, services)
    with pytest.raises(SinkUnavailable):
        await exporter.export_events()
    assert exporter.events_cursor is None and exporter.status()["lastError"]["what"] == "events"
    sink.fail = False
    assert (await exporter.export_events())["appended"] == 5


@pytest.mark.anyio
async def test_context_sync_appends_changes_and_everything_once_a_day(tmp_path) -> None:
    services, clock = Services(), Clock()
    exporter = exporter_for(FileSink(tmp_path), services, clock=clock)
    first = await exporter.sync_context()
    assert first["full"] and first["written"] == {"fleets": 1, "vehicles": 5, "vehicleStates": 0}
    assert rows(tmp_path, "vehicles")[4] == {"id": "veh_4", "syncedAt": STAMP,
                                             "data": {"vehicleId": "veh_4", "fleetId": "flt_1"}}

    services.vehicles[2] = {**services.vehicles[2], "fleetId": "flt_2"}
    second = await exporter.sync_context()
    assert not second["full"]
    assert second["written"] == {"fleets": 0, "vehicles": 1, "vehicleStates": 0}
    assert rows(tmp_path, "vehicles")[-1]["data"]["fleetId"] == "flt_2"

    # A day later everything is written again, so the 7-day expiry never drops a vehicle.
    clock.now = NOW + timedelta(hours=24)
    third = await exporter.sync_context()
    assert third["full"] and third["written"]["vehicles"] == 5


@pytest.mark.anyio
async def test_failed_sync_is_retried_in_full(tmp_path) -> None:
    class Flaky(FileSink):
        fail = True

        async def append(self, table, rows):
            if self.fail and table == "vehicles":
                raise SinkUnavailable("down")
            await super().append(table, rows)

    sink = Flaky(tmp_path)
    exporter = exporter_for(sink, Services())
    with pytest.raises(SinkUnavailable):
        await exporter.sync_context()
    assert exporter.status()["lastError"]["what"] == "context sync"
    sink.fail = False
    # The vehicles that never reached the sink are written now; the fleet already was.
    assert (await exporter.sync_context())["written"]["vehicles"] == 5


def test_http_errors_follow_the_outbox_retry_rules(tmp_path) -> None:
    services = Services()
    app = build_app(exporter_for(FileSink(tmp_path), services), run_background=False)
    with TestClient(app) as client:
        assert client.post("/v1/exports/incident-changes", json=CHANGE).status_code == 202
        # Unknown incident: 410, so the outbox gives up instead of retrying.
        gone = client.post("/v1/exports/incident-changes", json={**CHANGE, "incidentId": "inc_9"})
        assert gone.status_code == 410 and gone.json()["detail"]["code"] == "INCIDENT_GONE"
        assert client.post("/v1/exports/events").json()["appended"] == 5
        assert client.post("/v1/exports/flush").json()["failed"] == {}
        # signal-correlation down: 503, so the outbox retries later.
        services.down.update({"signal-correlation", "telematics-event"})
        assert client.post("/v1/exports/incident-changes", json=CHANGE).status_code == 503
        assert client.post("/v1/exports/events").status_code == 503
        bad = client.post("/v1/exports/incident-changes", json={**CHANGE, "incidentId": "../x"})
        assert bad.status_code == 422
        status = client.get("/v1/exports/status").json()
        assert status["incidentsExported"] == 1 and status["sink"]["kind"] == "file"
        assert status["eventsExported"] == 5
        assert status["lastError"]["what"] == "events"


@pytest.mark.anyio
async def test_file_sink_rejects_unknown_tables_and_unsafe_topics(tmp_path) -> None:
    sink = FileSink(tmp_path)
    with pytest.raises(ValueError):
        await sink.append("../escape", [{}])
    with pytest.raises(ValueError):
        await sink.publish("../escape", {}, ordering_key="k", attributes={})


def test_latest_views_keep_the_newest_row_per_key() -> None:
    sql = TABLES["incidents"].view_sql("fleetops")
    assert "PARTITION BY incidentId ORDER BY sourceVersion DESC, exportedAt DESC" in sql
    assert "FROM `fleetops.incidents`" in sql and sql.endswith("WHERE rowRank = 1")
    assert TABLES["events"].expire_days == 7 and TABLES["incidents"].expire_days is None


# --- GCP sink, against fakes ---------------------------------------------------------------


class FakeWriter:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.loads: list[tuple[str, list]] = []
        self.fail: set[str] = set()

    def create(self, table) -> None:
        self.created.append(table.name)

    def load(self, table, rows) -> None:
        if table.name in self.fail:
            raise RuntimeError("quota exceeded")
        self.loads.append((table.name, [r["n"] for r in rows]))


class FakeFuture:
    def __init__(self, error: Exception | None) -> None:
        self.error = error

    def result(self, timeout: float) -> str:
        if self.error:
            raise self.error
        return "msg-1"


class FakePublisher:
    def __init__(self) -> None:
        self.published, self.resumed, self.error = [], [], None

    def publish(self, topic, data, ordering_key="", **attrs):
        self.published.append((topic, json.loads(data), ordering_key, attrs))
        return FakeFuture(self.error)

    def resume_publish(self, topic, ordering_key):
        self.resumed.append((topic, ordering_key))


@pytest.mark.anyio
async def test_gcp_sink_buffers_rows_until_a_flush_loads_them() -> None:
    writer = FakeWriter()
    sink = GcpSink("demo-project", writer=writer, publisher=FakePublisher())
    await sink.append("events", [{"n": 1}, {"n": 2}])
    await sink.append("vehicles", [{"n": 3}])
    assert writer.loads == [] and sink.describe()["bufferedRows"] == {"events": 2, "vehicles": 1}

    assert await sink.flush() == {"loaded": {"events": 2, "vehicles": 1}, "failed": {}}
    assert writer.loads == [("events", [1, 2]), ("vehicles", [3])]
    await sink.append("events", [{"n": 4}])
    await sink.flush()
    assert writer.created == ["events", "vehicles"]   # each table is created once
    assert sink.describe()["bufferedRows"] == {}


@pytest.mark.anyio
async def test_gcp_sink_keeps_rows_of_a_failed_load_in_order(monkeypatch) -> None:
    writer = FakeWriter()
    sink = GcpSink("demo-project", writer=writer, publisher=FakePublisher())
    await sink.append("events", [{"n": 1}, {"n": 2}])
    writer.fail.add("events")
    result = await sink.flush()
    assert result["loaded"] == {} and "quota exceeded" in result["failed"]["events"]

    await sink.append("events", [{"n": 3}])
    writer.fail.clear()
    await sink.flush()
    assert writer.loads == [("events", [1, 2, 3])]

    # If BigQuery stays unreachable, the buffer is capped and the oldest rows go first.
    monkeypatch.setattr("cloud_exporter.sinks.MAX_BUFFERED_ROWS", 3)
    await sink.append("events", [{"n": n} for n in range(10, 15)])
    assert sink.describe()["droppedRows"] == 2
    await sink.flush()
    assert writer.loads[-1] == ("events", [12, 13, 14])


@pytest.mark.anyio
async def test_gcp_sink_rejects_unknown_tables() -> None:
    sink = GcpSink("demo-project", writer=FakeWriter(), publisher=FakePublisher())
    with pytest.raises(ValueError):
        await sink.append("incident_notes", [{}])


@pytest.mark.anyio
async def test_gcp_sink_publishes_with_ordering_and_resumes_after_a_failure() -> None:
    publisher = FakePublisher()
    sink = GcpSink("demo-project", writer=FakeWriter(), publisher=publisher)
    await sink.publish("fleetops-incidents", {"a": 1}, ordering_key="inc_1",
                       attributes={"step": "detected"})
    assert publisher.published == [("projects/demo-project/topics/fleetops-incidents",
                                     {"a": 1}, "inc_1", {"step": "detected"})]

    publisher.error = RuntimeError("deadline exceeded")
    with pytest.raises(SinkUnavailable):
        await sink.publish("fleetops-incidents", {}, ordering_key="inc_1", attributes={})
    # The paused ordering key is resumed so the outbox's retry can be published.
    assert publisher.resumed == [("projects/demo-project/topics/fleetops-incidents", "inc_1")]
