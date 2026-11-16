import os
from pathlib import Path

from fleetops_runtime import Database, build_app, database_url_for
from fleetops_runtime.loader import load_service

ROOT = Path(__file__).resolve().parent

service = load_service(
    Path(os.environ.get("FLEETOPS_SERVICE_PATH", "/app/service")),
    Path(os.environ.get("FLEETOPS_MIGRATIONS_ROOT", ROOT / "database")),
)
database = (
    Database(database_url_for(service.contract.slug), service.migrations_dir)
    if service.migrations_dir is not None
    else None
)
app = build_app(service.contract, service.handlers, database=database)
