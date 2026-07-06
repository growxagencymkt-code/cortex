"""API FastAPI: healthcheck, retrieval, chat, inbox y paneles (F2/F4)."""

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


def test_retrieve_rejects_empty_query() -> None:
    # 422 antes de tocar la base: validación de entrada.
    assert _client().post("/api/retrieve", json={"query": "   "}).status_code == 422


def test_retrieve_degrades_gracefully_without_db() -> None:
    # Sin Postgres alcanzable, la memoria no está disponible → 503 (no 500).
    resp = _client().post("/api/retrieve", json={"query": "presupuesto"})
    assert resp.status_code == 503


def test_chat_rejects_empty_query() -> None:
    # 422 antes de tocar la base ni el proveedor.
    assert _client().post("/api/chat", json={"query": "   "}).status_code == 422


def test_surfaces_degrade_without_db() -> None:
    # Sin Postgres, chat/inbox degradan a 503 (no 500, no cuelgan).
    client = _client()
    assert client.post("/api/chat", json={"query": "presupuesto"}).status_code == 503
    assert client.get("/api/inbox").status_code == 503


def test_unknown_panel_is_404_or_503() -> None:
    # Panel inexistente: 404 con DB, 503 sin ella (la memoria se construye antes).
    assert _client().get("/api/panels/inexistente").status_code in (404, 503)


def test_panel_projections_match_web_contract() -> None:
    # Las proyecciones (puras) que alinean el shape del panel con lo que lee la web.
    from cortex.api.app import _project_commitments, _project_economy, _project_map

    commitments = _project_commitments(
        {
            "vigentes": {"owed_by_me": [{"what": "x", "direction": "owed_by_me"}]},
            "en_riesgo": {},
            "incumplidos": {},
            "counts": {"total": 1},
        }
    )
    assert isinstance(commitments["vigentes"], list)
    assert commitments["vigentes"][0]["direction"] == "owed_by_me"

    economy = _project_economy({"savings_estimate_usd": 5.0, "cost_usd": 0.0})
    assert economy["savings_usd"] == 5.0

    op_map = _project_map(
        {
            "as_is": {"entities_by_kind": {"person": 2}, "relations_by_rel": {"emailed": 1}},
            "to_be": {},
        }
    )
    assert isinstance(op_map["as_is"], list)
    assert any(row["clave"] == "person" for row in op_map["as_is"])
