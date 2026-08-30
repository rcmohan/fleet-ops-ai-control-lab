from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI

from .factory import build_app


def _load_module(path: Path, *, package: bool = False):
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", path.parent.name)
    module_name = f"fleetops_service_{safe_name}_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
        submodule_search_locations=[str(path.parent)] if package else None,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load service module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_service_app(service_path: Path) -> FastAPI:
    app_file = service_path / "app.py"
    if app_file.exists():
        module = _load_module(app_file, package=True)
        return module.create_app()

    contract_file = service_path / "contract.py"
    if contract_file.exists():
        module = _load_module(contract_file)
        return build_app(module.CONTRACT)

    raise RuntimeError(
        f"Service {service_path} must contain app.py or contract.py"
    )
