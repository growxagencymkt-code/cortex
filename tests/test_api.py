"""Esqueleto FastAPI: healthcheck real + placeholders 501."""

from __future__ import annotations

from fastapi.testclient import TestClient

from cortex.api.app import create_app
from cortex.settings import Settings


def _client() -> TestClient:
    settings = Settings(
        postgres_dsn="postgresql+psycopg://cortex:cortex@127.0.0.1:59999/cortex",  # sin DB en tests
        _env_file=None,  # type: ignore[call-arg]
    )
    return TestClient(create_app(settings))


def test_health_is_real_and_tolerates_db_down() -> None:
    response = _client().get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] in ("ok", "unreachable")
    assert body["pipeline_ver"]
    assert body["version"]


def test_root_serves_status_page() -> None:
    response = _client().get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "CORTEX" in response.text or "COR" in response.text


def test_placeholder_surfaces_return_501() -> None:
    client = _client()
    assert client.post("/api/chat").status_code == 501
    assert client.get("/api/inbox").status_code == 501
    assert client.get("/api/panels/agentes").status_code == 501
