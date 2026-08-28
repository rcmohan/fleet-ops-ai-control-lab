import importlib.util
import os
from pathlib import Path

from fleetops_runtime import build_app


def _load_contract():
    service_path = Path(os.environ.get("FLEETOPS_SERVICE_PATH", "/app/service"))
    contract_file = service_path / "contract.py"
    spec = importlib.util.spec_from_file_location("fleetops_service_contract", contract_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load service contract: {contract_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CONTRACT


app = build_app(_load_contract())

