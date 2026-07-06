"""Esqueleto FastAPI de CORTEX.

F0: healthcheck real (proceso vivo + conectividad a Postgres) y placeholders
501 para las tres superficies de la interfaz humana (sección 11):
conversación, bandeja de decisiones y paneles. Se implementan en F2/F4.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cortex import __version__
from cortex.agents.candidates import mail_responder_spec
from cortex.api.service import MemoryService
from cortex.events.models import EventIn
from cortex.orchestrator.panels import (
    agents_panel,
    build_decision_inbox,
    card_to_api,
    commitments_panel,
    economy_panel,
    operative_map_panel,
)
from cortex.events.store import postgres_store_from_dsn
from cortex.extraction.providers import build_inference_client
from cortex.memory.answer import GroundedAnswer, answer_from_retrieval
from cortex.memory.retrieval import RetrievalResult
from cortex.settings import Settings, get_settings


class RetrieveRequest(BaseModel):
    """Cuerpo de POST /api/retrieve."""

    query: str


class ChatRequest(BaseModel):
    """Cuerpo de POST /api/chat."""

    query: str


class DecideRequest(BaseModel):
    """Cuerpo de POST /api/inbox/{card_id}/decide."""

    choice: str
    note: str = ""


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
  <div class="phase">Fases <b>F0–F4</b> vivas — log de eventos, memoria con evidencia, recuperación
  híbrida, chat fundamentado, bandeja de decisiones y paneles (§8, §11). Generación con proveedor
  configurable (NVIDIA NIM / compatible OpenAI); sin proveedor, respuesta extractiva $0.</div>
  <div class="api">
    <div class="row"><span class="m">GET</span><span class="p">/health</span><span class="st live">vivo</span></div>
    <div class="row"><span class="m">POST</span><span class="p">/api/retrieve</span><span class="st live">recuperación</span></div>
    <div class="row"><span class="m">POST</span><span class="p">/api/chat</span><span class="st live">respuesta fundamentada</span></div>
    <div class="row"><span class="m">POST</span><span class="p">/api/ingest/meeting</span><span class="st live">ingesta</span></div>
    <div class="row"><span class="m">GET</span><span class="p">/api/inbox</span><span class="st live">decisiones</span></div>
    <div class="row"><span class="m">GET</span><span class="p">/api/panels/{'{'}panel{'}'}</span><span class="st live">paneles</span></div>
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
    memory = MemoryService(cfg)

    # Interfaz de operador (SPA compilada). Si hay build, la raíz sirve la app;
    # si no, cae a la página de estado. Same-origin: la SPA llama /api/* y /health.
    web_dist = Path(cfg.web_dist_dir)
    spa_index = web_dist / "index.html"
    spa_available = spa_index.is_file()
    if spa_available and (web_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(web_dist / "assets")), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def root() -> HTMLResponse:
        """Raíz: la SPA de operador (chat + bandeja + paneles) si está compilada,
        o la página de estado on-brand como respaldo."""
        if spa_available:
            return HTMLResponse(content=spa_index.read_text(encoding="utf-8"))
        return HTMLResponse(content=_STATUS_PAGE.replace("__VERSION__", __version__))

    @app.get("/status", response_class=HTMLResponse)
    def status_page() -> HTMLResponse:
        """Página de estado on-brand con la salud real y la superficie de API."""
        return HTMLResponse(content=_STATUS_PAGE.replace("__VERSION__", __version__))

    @app.get("/health")
    def health() -> dict[str, Any]:
        """Healthcheck real: proceso vivo + estado de la base + versión de pipeline."""
        return {
            "status": "ok",
            "version": __version__,
            "pipeline_ver": cfg.pipeline_ver,
            "db": _db_status(cfg),
            # Diagnóstico (sin secretos): ¿el proceso ve el proveedor de inferencia?
            "inference": {
                "configured": bool(cfg.inference_base_url and cfg.core_model),
                "base_url_set": bool(cfg.inference_base_url),
                "core_model_set": bool(cfg.core_model),
            },
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
            return memory.retrieve(query)
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
        memory.invalidate()  # la memoria cacheada quedó obsoleta con el evento nuevo
        return {"inserted": True, "external_id": ext_id, "event_id": persisted.id}

    @app.post("/api/chat")
    def chat(body: ChatRequest) -> GroundedAnswer:
        """Superficie 11.1 — respuesta conversacional FUNDAMENTADA (§8, §11.1).

        Recupera evidencia de la memoria y genera una respuesta citada con el
        núcleo cognitivo (proveedor configurado). Sin evidencia dice que no sabe;
        sin proveedor (o ante un fallo de red) cae a una respuesta extractiva
        determinista ($0). Nunca inventa fuera de la evidencia (principio 3).
        """
        query = body.query.strip()
        if not query:
            raise HTTPException(status_code=422, detail="query vacía")
        try:
            retrieval = memory.retrieve(query)
        except Exception as exc:  # p.ej. Postgres no disponible
            raise HTTPException(status_code=503, detail=f"memoria no disponible: {exc}") from exc
        inference = build_inference_client(cfg, role="core")
        try:
            return answer_from_retrieval(retrieval, inference=inference)
        except Exception:
            # El proveedor falló (red/timeout): degradá a extractivo, nunca 500.
            return answer_from_retrieval(retrieval, inference=None)

    @app.get("/api/inbox")
    def inbox() -> dict[str, Any]:
        """Superficie 11.2 — bandeja de decisiones (§11.2).

        Tarjetas derivadas de la memoria: alertas de compromiso (por vencer /
        vencidos, con evidencia) y desambiguaciones pendientes. Anti-inercia
        aplicado por la cola. Ordenadas por urgencia.
        """
        now = datetime.now(tz=UTC)
        try:
            snap = memory.snapshot()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"memoria no disponible: {exc}") from exc
        box = build_decision_inbox(snap.memory, now=now, pipeline_ver=cfg.pipeline_ver)
        cards = [card_to_api(c) for c in box.pending()]
        return {"cards": cards, "count": len(cards)}

    @app.post("/api/inbox/{card_id}/decide")
    def decide(card_id: str, body: DecideRequest) -> dict[str, Any]:
        """Registra la elección humana sobre una tarjeta (§11.2).

        La decisión humana es fuente CONFIABLE de instrucción: se persiste como
        evento append-only `source='human_ui'` (auditable, reconstruible). No muta
        el log de negocio; agrega un evento nuevo (principio 1).
        """
        if body.choice not in ("approve", "edit", "reject"):
            raise HTTPException(status_code=422, detail="choice inválida")
        event = EventIn(
            ts=datetime.now(tz=UTC),
            source="human_ui",
            type="human_decision",
            external_id=None,
            actor="founder",
            payload={"card_id": card_id, "choice": body.choice, "note": body.note},
            pipeline_ver=cfg.pipeline_ver,
        )
        try:
            store = postgres_store_from_dsn(cfg.postgres_dsn)
            store.append(event)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"no se pudo registrar: {exc}") from exc
        memory.invalidate()
        return {"ok": True, "card_id": card_id, "choice": body.choice}

    @app.get("/api/panels/{panel_name}")
    def panels(panel_name: str) -> dict[str, Any]:
        """Superficie 11.3 — paneles (mapa operativo, agentes, compromisos, economía)."""
        now = datetime.now(tz=UTC)
        try:
            snap = memory.snapshot()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"memoria no disponible: {exc}") from exc
        name = panel_name.lower()
        if name == "commitments":
            return _project_commitments(commitments_panel(snap.memory, now=now))
        if name == "agents":
            # Registro de agentes diseñados (F4): por ahora el mail-responder.
            return agents_panel([mail_responder_spec()])
        if name == "economy":
            return _project_economy(economy_panel())
        if name in ("map", "operative", "operative_map"):
            return _project_map(operative_map_panel(snap.memory))
        raise HTTPException(status_code=404, detail=f"panel desconocido: {panel_name}")

    return app


def _project_commitments(panel: dict[str, Any]) -> dict[str, Any]:
    """Aplana los grupos por dirección a listas (la web espera arrays planos),
    conservando `direction` en cada item y los `counts` originales."""
    out: dict[str, Any] = {"counts": panel.get("counts", {})}
    for group in ("vigentes", "en_riesgo", "incumplidos"):
        by_dir = panel.get(group, {})
        items: list[dict[str, Any]] = []
        if isinstance(by_dir, dict):
            for direction, rows in by_dir.items():
                for row in rows:
                    items.append({**row, "direction": row.get("direction", direction)})
        out[group] = items
    return out


def _project_economy(panel: dict[str, Any]) -> dict[str, Any]:
    """Agrega alias `savings_usd` que la web lee, sin perder la clave canónica."""
    return {**panel, "savings_usd": panel.get("savings_estimate_usd", 0.0)}


def _project_map(panel: dict[str, Any]) -> dict[str, Any]:
    """Proyecta `as_is` (dict de conteos) a filas planas para la web."""
    as_is = panel.get("as_is", {})
    by_kind = as_is.get("entities_by_kind", {}) if isinstance(as_is, dict) else {}
    by_rel = as_is.get("relations_by_rel", {}) if isinstance(as_is, dict) else {}
    rows = [{"tipo": "entidad", "clave": k, "conteo": v} for k, v in by_kind.items()]
    rows += [{"tipo": "relación", "clave": k, "conteo": v} for k, v in by_rel.items()]
    return {"as_is": rows, "resumen": as_is, "to_be": panel.get("to_be", {})}


# Instancia para `uvicorn cortex.api.app:app` (Dockerfile / docker compose).
app = create_app()
