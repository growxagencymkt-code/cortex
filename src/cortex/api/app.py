"""Esqueleto FastAPI de CORTEX.

F0: healthcheck real (proceso vivo + conectividad a Postgres) y placeholders
501 para las tres superficies de la interfaz humana (sección 11):
conversación, bandeja de decisiones y paneles. Se implementan en F2/F4.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException

from cortex import __version__
from cortex.settings import Settings, get_settings

_NOT_IMPLEMENTED = "Aún no implementado en F0 (ver docs/SYSTEM_PROMPT.md, sección 13)."


def _db_status(settings: Settings) -> str:
    """Chequeo real de conectividad a Postgres (sin tumbar el health si falta)."""
    try:
        engine = sa.create_engine(settings.postgres_dsn, connect_args={"connect_timeout": 2})
        try:
            with engine.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
            return "ok"
        finally:
            engine.dispose()
    except Exception:
        return "unreachable"


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings if settings is not None else get_settings()
    app = FastAPI(title="CORTEX", version=__version__)

    @app.get("/health")
    def health() -> dict[str, Any]:
        """Healthcheck real: proceso vivo + estado de la base + versión de pipeline."""
        return {
            "status": "ok",
            "version": __version__,
            "pipeline_ver": cfg.pipeline_ver,
            "db": _db_status(cfg),
        }

    @app.post("/api/chat", status_code=501)
    def chat_placeholder() -> dict[str, str]:
        """Superficie 11.1 — conversación sobre la memoria (F2)."""
        raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED)

    @app.get("/api/inbox", status_code=501)
    def inbox_placeholder() -> dict[str, str]:
        """Superficie 11.2 — bandeja de decisiones (F4)."""
        raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED)

    @app.get("/api/panels/{panel_name}", status_code=501)
    def panels_placeholder(panel_name: str) -> dict[str, str]:
        """Superficie 11.3 — paneles (mapa operativo, agentes, compromisos, economía)."""
        raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED)

    return app


# Instancia para `uvicorn cortex.api.app:app` (Dockerfile / docker compose).
app = create_app()
