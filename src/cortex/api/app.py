"""Esqueleto FastAPI de CORTEX.

F0: healthcheck real (proceso vivo + conectividad a Postgres) y placeholders
501 para las tres superficies de la interfaz humana (sección 11):
conversación, bandeja de decisiones y paneles. Se implementan en F2/F4.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from cortex import __version__
from cortex.events.models import EventIn
from cortex.events.store import postgres_store_from_dsn
from cortex.memory.retrieval import RetrievalResult, answer_query
from cortex.settings import Settings, get_settings


class RetrieveRequest(BaseModel):
    """Cuerpo de POST /api/retrieve."""

    query: str


class IngestMeetingRequest(BaseModel):
    """Cuerpo de POST /api/ingest/meeting — lo que el Copiloto de Reuniones publica
    al cerrar una reunión. Se normaliza a un evento `meeting.transcript`."""

    external_id: str
    user: str = ""
    day: str = ""
    title: str = ""
    platform: str = ""
    topic: str = ""
    started_at: float | None = None
    ended_at: float | None = None
    duration_s: float = 0.0
    transcript: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)

_NOT_IMPLEMENTED = "Aún no implementado en F0 (ver docs/SYSTEM_PROMPT.md, sección 13)."

# Página de estado (raíz). CORTEX en F0/F1 es un backend: la interfaz de operador
# (chat + bandeja + paneles, §11) es F2/F4. Esta página muestra estado real y la
# superficie de API viva, para que la URL cargue algo honesto y on-brand.
_STATUS_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CORTEX — Estado del sistema</title>
<style>
  :root{--navy:#0B3A4A;--blue:#2D82A9;--cyan:#37B6C7;--green:#64B26A;--gold:#F2B541;--light:#BFEFF0;--gray:#8D9AA0}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:radial-gradient(1200px 600px at 70% -10%,#0f4a5e,#08222c 60%);color:#eaf6f8;min-height:100vh;padding:clamp(20px,5vw,64px);display:flex;flex-direction:column;align-items:center}
  .wrap{width:100%;max-width:860px}
  .brand{display:flex;align-items:center;gap:14px;margin-bottom:6px}
  .dot{width:14px;height:14px;border-radius:50%;background:var(--gray);box-shadow:0 0 0 4px rgba(255,255,255,.05)}
  .dot.ok{background:var(--green);box-shadow:0 0 16px var(--green)}
  .dot.bad{background:#e06a5a;box-shadow:0 0 16px #e06a5a}
  h1{font-size:clamp(28px,6vw,44px);letter-spacing:.18em;font-weight:700}
  h1 span{color:var(--gold)}
  .sub{color:var(--light);opacity:.85;margin:2px 0 28px;font-size:15px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:28px}
  .card{background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:18px 20px}
  .card .k{font-size:12px;text-transform:uppercase;letter-spacing:.12em;color:var(--gray)}
  .card .v{font-size:22px;font-weight:600;margin-top:6px;color:#fff}
  .card .v.ok{color:var(--green)} .card .v.bad{color:#e06a5a}
  .phase{background:linear-gradient(90deg,rgba(242,181,65,.12),rgba(55,182,199,.06));border:1px solid rgba(242,181,65,.25);border-radius:14px;padding:18px 20px;margin-bottom:28px}
  .phase b{color:var(--gold)}
  .api{background:rgba(0,0,0,.18);border:1px solid rgba(255,255,255,.07);border-radius:14px;overflow:hidden}
  .api .row{display:flex;align-items:center;gap:12px;padding:13px 18px;border-top:1px solid rgba(255,255,255,.05);font-size:14px}
  .api .row:first-child{border-top:none}
  .m{font:600 11px/1 ui-monospace,monospace;padding:4px 8px;border-radius:6px;background:var(--navy);color:var(--cyan);border:1px solid rgba(55,182,199,.3)}
  .p{font-family:ui-monospace,monospace;color:#dfeef1;flex:1}
  .st{font-size:12px;color:var(--gray)} .st.live{color:var(--green)}
  footer{margin-top:32px;color:var(--gray);font-size:12px;letter-spacing:.1em}
</style></head>
<body><div class="wrap">
  <div class="brand"><span id="dot" class="dot"></span><h1>COR<span>TEX</span></h1></div>
  <div class="sub">Cerebro operativo agentivo · event sourcing + memoria organizacional + simulador</div>
  <div class="grid">
    <div class="card"><div class="k">Estado</div><div class="v" id="status">…</div></div>
    <div class="card"><div class="k">Versión</div><div class="v" id="version">…</div></div>
    <div class="card"><div class="k">Pipeline</div><div class="v" id="pipe">…</div></div>
    <div class="card"><div class="k">Base de datos</div><div class="v" id="db">…</div></div>
  </div>
  <div class="phase">Fase actual <b>F0/F1</b> — backend vivo (log de eventos, memoria con evidencia, API de salud).
  La interfaz de operador (chat, bandeja de decisiones y paneles — §11) llega en <b>F2/F4</b>.</div>
  <div class="api">
    <div class="row"><span class="m">GET</span><span class="p">/health</span><span class="st live">vivo</span></div>
    <div class="row"><span class="m">POST</span><span class="p">/api/chat</span><span class="st">F2 · 501</span></div>
    <div class="row"><span class="m">GET</span><span class="p">/api/inbox</span><span class="st">F4 · 501</span></div>
    <div class="row"><span class="m">GET</span><span class="p">/api/panels/{'{'}panel{'}'}</span><span class="st">F2/F4 · 501</span></div>
    <div class="row"><span class="m">GET</span><span class="p">/docs</span><span class="st live">OpenAPI</span></div>
  </div>
  <footer>GROWX · CORTEX v__VERSION__</footer>
</div>
<script>
  fetch('/health').then(r=>r.json()).then(d=>{
    const ok=d.status==='ok';
    document.getElementById('dot').className='dot '+(ok?'ok':'bad');
    const s=document.getElementById('status');s.textContent=ok?'Operativo':'Degradado';s.className='v '+(ok?'ok':'bad');
    document.getElementById('version').textContent=d.version||'—';
    document.getElementById('pipe').textContent=d.pipeline_ver||'—';
    const db=document.getElementById('db');db.textContent=d.db==='ok'?'Conectada':'Sin conexión';db.className='v '+(d.db==='ok'?'ok':'bad');
  }).catch(()=>{document.getElementById('status').textContent='Sin respuesta';});
</script>
</body></html>"""


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

    @app.get("/", response_class=HTMLResponse)
    def status_page() -> HTMLResponse:
        """Página de estado on-brand (la raíz cargaba 404; ahora muestra salud real)."""
        return HTMLResponse(content=_STATUS_PAGE.replace("__VERSION__", __version__))

    @app.get("/health")
    def health() -> dict[str, Any]:
        """Healthcheck real: proceso vivo + estado de la base + versión de pipeline."""
        return {
            "status": "ok",
            "version": __version__,
            "pipeline_ver": cfg.pipeline_ver,
            "db": _db_status(cfg),
        }

    @app.post("/api/retrieve")
    def retrieve_endpoint(body: RetrieveRequest) -> RetrievalResult:
        """Superficie 11.1 (F2) — recuperación híbrida fundamentada (§8).

        Reconstruye la memoria desde el log y devuelve hechos (con evidencia) +
        chunks (con fuente/fecha). No genera lenguaje (eso es el núcleo con un
        proveedor): entrega el CONTEXTO fundamentado, costo $0. Sin evidencia,
        `answerable=False` y dice que no sabe.
        """
        query = body.query.strip()
        if not query:
            raise HTTPException(status_code=422, detail="query vacía")
        try:
            store = postgres_store_from_dsn(cfg.postgres_dsn)
            return answer_query(store, query)
        except HTTPException:
            raise
        except Exception as exc:  # p.ej. Postgres no disponible
            raise HTTPException(
                status_code=503, detail=f"memoria no disponible: {exc}"
            ) from exc

    @app.post("/api/ingest/meeting", status_code=201)
    def ingest_meeting(body: IngestMeetingRequest) -> dict[str, Any]:
        """Ingesta de una reunión del Copiloto como evento `meeting.transcript`.

        Idempotente por external_id (re-publicar la misma reunión no duplica). El
        payload observado es DATO (principio 3): el extractor lo analiza, nunca lo
        obedece. Alimenta el grafo (reunión/tema/compromisos/decisiones con evidencia).
        """
        ext_id = body.external_id.strip()
        if not ext_id:
            raise HTTPException(status_code=422, detail="external_id vacío")
        ts = (
            datetime.fromtimestamp(body.started_at, tz=UTC)
            if body.started_at
            else datetime.now(tz=UTC)
        )
        event = EventIn(
            ts=ts,
            source="meetings",
            type="meeting.transcript",
            external_id=ext_id,
            actor=body.user or None,
            payload=body.model_dump(),
            pipeline_ver=cfg.pipeline_ver,
        )
        try:
            store = postgres_store_from_dsn(cfg.postgres_dsn)
            persisted = store.append(event)
        except Exception as exc:  # p.ej. Postgres no disponible
            raise HTTPException(status_code=503, detail=f"no se pudo ingerir: {exc}") from exc
        if persisted is None:
            return {"inserted": False, "external_id": ext_id, "reason": "duplicate"}
        return {"inserted": True, "external_id": ext_id, "event_id": persisted.id}

    @app.post("/api/chat", status_code=501)
    def chat_placeholder() -> dict[str, str]:
        """Superficie 11.1 — generación conversacional (necesita proveedor; F2.1)."""
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
