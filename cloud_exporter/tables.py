"""The BigQuery tables the exporter appends to, and the views that read them.

Every table is append-only: a retry or a resync adds a row instead of updating one, so each
table has a `<table>_latest` view that keeps the newest row per key. Tables are partitioned by
day; raw telemetry and the context copies expire after a week (the context is rewritten in full
every day, so a vehicle never drops out of its view), while incidents and evidence are kept.

Schemas are deliberately flat at the top (the columns you filter and cluster on) with the
full record in a JSON column, so a new field in a service response needs no schema change.
"""

from __future__ import annotations

from dataclasses import dataclass

DAY_MS = 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[tuple[str, str], ...]   # (name, BigQuery type); all NULLABLE
    partition_by: str                      # a TIMESTAMP column
    cluster_by: tuple[str, ...]
    key: str                               # the latest view keeps one row per key
    newest_by: tuple[str, ...]             # ... the one that sorts first, all descending
    expire_days: int | None = None

    @property
    def view(self) -> str:
        return f"{self.name}_latest"

    def view_sql(self, dataset: str) -> str:
        return (
            f"SELECT * EXCEPT (rowRank) FROM (\n"
            f"  SELECT *, ROW_NUMBER() OVER (PARTITION BY {self.key} "
            f"ORDER BY {', '.join(f'{c} DESC' for c in self.newest_by)}) AS rowRank\n"
            f"  FROM `{dataset}.{self.name}`\n"
            f") WHERE rowRank = 1"
        )


def context(name: str) -> Table:
    return Table(name, (("id", "STRING"), ("syncedAt", "TIMESTAMP"), ("data", "JSON")),
                 partition_by="syncedAt", cluster_by=("id",), key="id", newest_by=("syncedAt",),
                 expire_days=7)


TABLES: dict[str, Table] = {table.name: table for table in (
    Table("events",
          (("eventId", "STRING"), ("vehicleId", "STRING"), ("eventType", "STRING"),
           ("severity", "STRING"), ("regionCode", "STRING"), ("observedAt", "TIMESTAMP"),
           ("receivedAt", "TIMESTAMP"), ("payload", "JSON"), ("synthetic", "BOOL"),
           ("exportedAt", "TIMESTAMP")),
          partition_by="observedAt", cluster_by=("vehicleId", "eventType"),
          key="eventId", newest_by=("exportedAt",), expire_days=7),
    Table("incidents",
          (("incidentId", "STRING"), ("vehicleId", "STRING"), ("ruleId", "STRING"),
           ("status", "STRING"), ("riskLevel", "STRING"), ("riskScore", "FLOAT64"),
           ("step", "STRING"), ("stepId", "INT64"), ("sourceVersion", "INT64"),
           ("exportedAt", "TIMESTAMP"), ("incident", "JSON")),
          partition_by="exportedAt", cluster_by=("incidentId",),
          key="incidentId", newest_by=("sourceVersion", "exportedAt")),
    Table("evidence",
          (("incidentId", "STRING"), ("vehicleId", "STRING"), ("step", "STRING"),
           ("sourceVersion", "INT64"), ("builtAt", "TIMESTAMP"), ("bundle", "JSON")),
          partition_by="builtAt", cluster_by=("incidentId",),
          key="incidentId", newest_by=("builtAt",)),
    context("fleets"),
    context("vehicles"),
    context("vehicleStates"),
)}
