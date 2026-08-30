from pathlib import Path

from fastapi.testclient import TestClient

from fleetops_runtime import load_service_app


ROOT = Path(__file__).resolve().parents[1]


def test_every_service_is_runnable_and_has_openapi() -> None:
    service_paths = sorted(
        path for path in (ROOT / "services").iterdir() if path.is_dir()
    )
    assert len(service_paths) == 16

    for service_path in service_paths:
        app = load_service_app(service_path)
        client = TestClient(app)

        health = client.get("/health/ready")
        assert health.status_code == 200
        assert health.json()["service"] == service_path.name

        schema = client.get("/openapi.json")
        assert schema.status_code == 200
        assert schema.json()["info"]["title"] == app.title
        domain_routes = [
            route
            for route in app.routes
            if route.path
            not in {
                "/docs",
                "/docs/oauth2-redirect",
                "/redoc",
                "/openapi.json",
                "/health/live",
                "/health/ready",
            }
        ]
        assert domain_routes, service_path.name
