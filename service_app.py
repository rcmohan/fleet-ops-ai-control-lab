import os
from pathlib import Path

from fleetops_runtime import load_service_app


service_path = Path(os.environ.get("FLEETOPS_SERVICE_PATH", "/app/service"))
app = load_service_app(service_path)
