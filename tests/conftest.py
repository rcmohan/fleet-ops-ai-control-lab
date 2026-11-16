import asyncio
import sys
from pathlib import Path

import pytest

from fleetops_runtime.loader import ServiceDefinition, load_service

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def anyio_backend():
    # psycopg's async driver cannot use the Proactor loop that Windows defaults to.
    if sys.platform == "win32":
        return ("asyncio", {"loop_factory": asyncio.SelectorEventLoop})
    return "asyncio"


def all_services() -> dict[str, ServiceDefinition]:
    definitions = (
        load_service(path.parent, ROOT / "database")
        for path in sorted((ROOT / "services").glob("*/contract.py"))
    )
    return {definition.contract.slug: definition for definition in definitions}
