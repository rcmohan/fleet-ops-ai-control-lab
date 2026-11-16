"""Loads a service folder (contract.py, optional handlers.py) and its migrations folder."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from .contracts import ServiceContract
from .handlers import HandlerRegistry


@dataclass(frozen=True)
class ServiceDefinition:
    contract: ServiceContract
    handlers: HandlerRegistry | None
    migrations_dir: Path | None


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    # Registered so dataclasses and pydantic can resolve the module by name.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_service(service_dir: Path, migrations_root: Path) -> ServiceDefinition:
    prefix = service_dir.name.replace("-", "_")
    contract = _load_module(service_dir / "contract.py", f"{prefix}_contract").CONTRACT
    handlers_file = service_dir / "handlers.py"
    handlers = (
        _load_module(handlers_file, f"{prefix}_handlers").HANDLERS
        if handlers_file.exists()
        else None
    )
    migrations_dir = migrations_root / contract.slug
    has_migrations = migrations_dir.is_dir() and any(migrations_dir.glob("*.sql"))
    return ServiceDefinition(contract, handlers, migrations_dir if has_migrations else None)
