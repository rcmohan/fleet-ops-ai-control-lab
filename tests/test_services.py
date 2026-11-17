import importlib.util
import re
from pathlib import Path

from fastapi.testclient import TestClient

from fleetops_runtime import build_app


ROOT = Path(__file__).resolve().parents[1]


def load_contract(path: Path):
    spec = importlib.util.spec_from_file_location(path.parent.name.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CONTRACT


def test_every_service_is_runnable_and_has_openapi() -> None:
    contract_files = sorted((ROOT / "services").glob("*/contract.py"))
    assert len(contract_files) == 16

    for contract_file in contract_files:
        contract = load_contract(contract_file)
        client = TestClient(build_app(contract))

        health = client.get("/health/ready")
        assert health.status_code == 200
        assert health.json()["service"] == contract.slug

        schema = client.get("/openapi.json")
        assert schema.status_code == 200
        assert schema.json()["info"]["title"] == contract.title
        assert len(contract.operations) > 0

        for operation in contract.operations:
            path = re.sub(r"{[^}]+}", "demo-id", operation.path)
            query = {
                parameter.name: "1" if parameter.schema_type == "integer" else "demo"
                for parameter in operation.parameters
                if parameter.location == "query" and parameter.required
            }
            headers = {
                parameter.name: "demo"
                for parameter in operation.parameters
                if parameter.location == "header" and parameter.required
            }
            response = client.request(
                operation.method,
                path,
                json=operation.request if operation.request is not None else None,
                params=query,
                headers=headers,
            )
            assert response.status_code == 200, (
                contract.slug,
                operation.operation_id,
                response.text,
            )


def test_gateway_prefix_serves_docs_under_service_path() -> None:
    contract = load_contract(ROOT / "services" / "approval" / "contract.py")
    client = TestClient(build_app(contract))
    gateway = {"X-Forwarded-Prefix": "/approval"}

    docs = client.get("/approval/docs", headers=gateway)
    assert docs.status_code == 200
    assert "/approval/openapi.json" in docs.text

    schema = client.get("/approval/openapi.json", headers=gateway)
    assert schema.status_code == 200
    assert schema.json()["servers"] == [{"url": "/approval"}]

    assert client.get("/approval/health/ready", headers=gateway).status_code == 200

    direct = client.get("/docs")
    assert direct.status_code == 200
    assert "'/openapi.json'" in direct.text

    forged = client.get("/docs", headers={"X-Forwarded-Prefix": "/approval'</script>"})
    assert "'/openapi.json'" in forged.text
