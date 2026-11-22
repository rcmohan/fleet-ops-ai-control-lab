"""Cloud exporter: sinks, incident snapshots, context sync, and the outbox-facing HTTP errors."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from cloud_exporter.app import build_app
from cloud_exporter.exporter import SCHEMA, Exporter
from cloud_exporter.sinks import FileSink, GcpSink, SinkUnavailable
from fleetops_runtime.services import ServiceClients

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
STAMP = "2026-11-18T09:00:00Z"
CHANGE = {"incidentId": "inc_1", "step": "scored", "stepId": 7, "at": "2026-11-18T08:59:00Z"}


class Services:
    """Fake signal-correlation, fleet-master, vehicle-master and digital-twin-context."""

    def __init__(self) -> None:
        self.incidents = {"inc_1": {"incidentId": "inc_1", "vehicleId": "veh_1",
                                    "status": "case_opened", "sourceVersion": 4,
                                    "events": [], "timeline": []}}
        self.vehicles = [{"vehicleId": f"veh_{n}", "fleetId": "flt_1"} for n in range(5)]
        self.down: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host in self.down:
            raise httpx.ConnectError("refused", request=request)
        if path.startswith("/v1/correlation/incidents/"):
            incident = self.incidents.get(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=incident) if incident else httpx.Response(404)
        items = {"/v1/fleets": [{"fleetId": "flt_1"}], "/v1/vehicles": self.vehicles,
                 "/v1/digital-twins/vehicles": []}[path]
        start = int(request.url.params.get("cursor") or 0)
        page = items[start:start + 2]   # small pages, to exercise the cursor
        more = start + 2 < len(items)
        return httpx.Response(200, json={"items": page,
                                         "nextCursor": str(start + 2) if more else None})


def exporter_for(sink, services: Services) -> Exporter:
    clients = ServiceClients(transport=httpx.MockTransport(services))
    return Exporter(sink, clients, context_interval=0, clock=lambda: NOW)


def topic_lines(root) -> list[dict]:
    path = root / "topics" / "fleetops-incidents.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def doc(root, collection: str, doc_id: str) -> dict:
    return json.loads((root / "collections" / collection / f"{doc_id}.json").read_text())


@pytest.mark.anyio
async def test_incident_change_writes_snapshot_and_publishes(tmp_path) -> None:
    exporter = exporter_for(FileSink(tmp_path), Services())
    await exporter.export_incident_change(CHANGE)
    await exporter.export_incident_change(CHANGE)   # a redelivery is harmless

    stored = doc(tmp_path, "incidents", "inc_1")
    assert stored["status"] == "case_opened" and stored["exportedAt"] == STAMP
    first, second = topic_lines(tmp_path)
    assert first["orderingKey"] == "inc_1"
    assert first["attributes"] == {"incidentId": "inc_1", "vehicleId": "veh_1",
                                   "step": "scored", "status": "case_opened",
                                   "sourceVersion": "4", "dedupeKey": "inc_1:7"}
    assert first["data"]["schema"] == SCHEMA and first["data"]["change"] == CHANGE
    assert first["data"]["incident"]["status"] == "case_opened"
    assert second["attributes"]["dedupeKey"] == first["attributes"]["dedupeKey"]
    assert exporter.status()["incidentsExported"] == 2


@pytest.mark.anyio
async def test_context_sync_pages_and_writes_only_changes(tmp_path) -> None:
    services = Services()
    exporter = exporter_for(FileSink(tmp_path), services)
    first = await exporter.sync_context()
    assert first["written"] == {"fleets": 1, "vehicles": 5, "vehicleStates": 0}
    assert doc(tmp_path, "vehicles", "veh_4")["syncedAt"] == STAMP

    services.vehicles[2] = {**services.vehicles[2], "fleetId": "flt_2"}
    second = await exporter.sync_context()
    assert second["written"] == {"fleets": 0, "vehicles": 1, "vehicleStates": 0}
    assert doc(tmp_path, "vehicles", "veh_2")["fleetId"] == "flt_2"


@pytest.mark.anyio
async def test_failed_sync_is_retried_in_full(tmp_path) -> None:
    class Flaky(FileSink):
        fail = True

        async def put(self, collection, documents):
            if self.fail and collection == "vehicles":
                raise SinkUnavailable("down")
            await super().put(collection, documents)

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
        # signal-correlation down: 503, so the outbox retries later.
        services.down.add("signal-correlation")
        down = client.post("/v1/exports/incident-changes", json=CHANGE)
        assert down.status_code == 503
        bad = client.post("/v1/exports/incident-changes", json={**CHANGE, "incidentId": "../x"})
        assert bad.status_code == 422
        status = client.get("/v1/exports/status").json()
        assert status["incidentsExported"] == 1 and status["sink"]["kind"] == "file"
        assert status["lastError"]["what"] == "incident inc_1"


@pytest.mark.anyio
async def test_file_sink_rejects_unsafe_ids(tmp_path) -> None:
    with pytest.raises(ValueError):
        await FileSink(tmp_path).put("vehicles", {"../escape": {}})


# --- GCP sink, against fake clients --------------------------------------------------------


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


class FakeFirestore:
    def __init__(self) -> None:
        self.commits: list[list[tuple[str, str, dict]]] = []

    def collection(self, name):
        class Collection:
            def document(self, doc_id):
                return (name, doc_id)

        return Collection()

    def batch(self):
        commits = self.commits

        class Batch:
            def __init__(self) -> None:
                self.writes = []

            def set(self, ref, document):
                self.writes.append((*ref, document))

            def commit(self):
                commits.append(self.writes)

        return Batch()


@pytest.mark.anyio
async def test_gcp_sink_publishes_with_ordering_and_batches_writes() -> None:
    publisher, store = FakePublisher(), FakeFirestore()
    sink = GcpSink("demo-project", publisher=publisher, firestore_client=store)
    await sink.publish("fleetops-incidents", {"a": 1}, ordering_key="inc_1",
                       attributes={"step": "detected"})
    assert publisher.published == [("projects/demo-project/topics/fleetops-incidents",
                                     {"a": 1}, "inc_1", {"step": "detected"})]

    await sink.put("vehicles", {f"veh_{n}": {"n": n} for n in range(401)})
    assert [len(batch) for batch in store.commits] == [400, 1]
    assert store.commits[1][0] == ("vehicles", "veh_400", {"n": 400})

    publisher.error = RuntimeError("deadline exceeded")
    with pytest.raises(SinkUnavailable):
        await sink.publish("fleetops-incidents", {}, ordering_key="inc_1", attributes={})
    # The paused ordering key is resumed so the outbox's retry can be published.
    assert publisher.resumed == [("projects/demo-project/topics/fleetops-incidents", "inc_1")]
