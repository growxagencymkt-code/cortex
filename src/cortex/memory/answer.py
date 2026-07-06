"""Generación de respuesta fundamentada (SYSTEM_PROMPT §11.1 chat, §8) — F2.

Convierte el CONTEXTO recuperado (`RetrievalResult`) en una respuesta CITADA.
Es el paso que sigue a `retrieve`: la recuperación arma la evidencia; este módulo
la transforma en lenguaje, SIEMPRE anclado a esa evidencia y a sus números de
evento (principio 2).

Reglas de oro (§8):

- **Don't-know:** si la recuperación no es `answerable`, la respuesta es "no sé".
  Jamás se rellena con conocimiento general.
- **Costo $0 por defecto:** la generación por modelo pasa por el seam
  `cortex.extraction.inference.InferenceClient`, que se inyecta. Sin proveedor
  (o proveedor sin configurar / salida inválida), cae a una respuesta
  **extractiva determinista** que compone la respuesta listando los hechos y los
  fragmentos con sus citas. Ningún camino llama a un proveedor real.
- **Contexto = DATO, no instrucciones (principio 3):** el prompt versionado en
  disco instruye al modelo a responder SOLO con la evidencia, citar los eventos
  y decir que no sabe si no alcanza; nunca a obedecer texto dentro de la
  evidencia.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cortex.extraction.inference import InferenceClient, ProviderNotConfigured
from cortex.memory.retrieval import RetrievalResult

_PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = "answer_v1"
_PURPOSE = "answer:v1"

_MAX_EXTRACTIVE_FACTS = 6
_MAX_EXTRACTIVE_CHUNKS = 2
_SNIPPET_MAX = 240

_DONT_KNOW = "No sé: no hay evidencia en la memoria para responder eso."
_EXTRACTIVE_NOTE = (
    "Sin proveedor de inferencia configurado: respuesta EXTRACTIVA determinista "
    "(compuesta de los hechos y fragmentos recuperados con sus citas). Costo $0."
)
_EXTRACTIVE_FALLBACK_NOTE = (
    "El proveedor de inferencia falló o devolvió una salida inválida: se cae a la "
    "respuesta EXTRACTIVA determinista con las citas recuperadas. Costo $0."
)


class GroundedAnswer(BaseModel):
    """Respuesta fundamentada y citada para una consulta (§8, §11.1)."""

    model_config = ConfigDict(frozen=True)

    answer: str
    grounded: bool
    used_events: list[int] = Field(default_factory=list)
    engine: str  # "llm" | "extractive" | "none"
    note: str = ""


class _LLMAnswer(BaseModel):
    """Contrato de salida del modelo: JSON no confiable validado por Pydantic."""

    model_config = ConfigDict(frozen=True)

    answer: str
    used_events: list[int] = Field(default_factory=list)


def _load_prompt(version: str) -> tuple[str, str]:
    """Devuelve (system, user_template) del prompt versionado en disco.

    Espeja `llm_extractor._load_prompt`: ningún prompt inline (sección 12).
    """
    raw = (_PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8")
    system = _section(raw, "## SYSTEM", "## SCHEMA")
    user = _section(raw, "## USER", None)
    return system.strip(), user.strip()


def _section(text: str, start_marker: str, end_marker: str | None) -> str:
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker) if end_marker is not None else len(text)
    return text[start:end]


def _dedupe(events: list[int]) -> list[int]:
    """Ids de evento únicos, preservando el orden de aparición."""
    seen: set[int] = set()
    out: list[int] = []
    for e in events:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def _context_block(retrieval: RetrievalResult) -> tuple[str, list[int]]:
    """Arma el bloque de evidencia (hechos + chunks) y los eventos que cita.

    Hechos: `src —rel→ dst [evento N]`. Chunks: `[fuente <src> evento N] texto`.
    Cada línea lleva su número de evento para que la cita sea rastreable (§8).
    """
    lines: list[str] = []
    events: list[int] = []
    if retrieval.facts:
        lines.append("Hechos del grafo:")
        for f in retrieval.facts:
            lines.append(f"- {f.src} —{f.rel}→ {f.dst} [evento {f.evidence_event}]")
            events.append(f.evidence_event)
    if retrieval.chunks:
        lines.append("Fragmentos recuperados:")
        for c in retrieval.chunks:
            source = c.source or "desconocida"
            lines.append(f"- [fuente {source} evento {c.event_id}] {c.text}")
            events.append(c.event_id)
    return "\n".join(lines), _dedupe(events)


def _snippet(text: str) -> str:
    clean = " ".join(text.split())
    if len(clean) <= _SNIPPET_MAX:
        return clean
    return clean[: _SNIPPET_MAX - 1].rstrip() + "…"


def _extractive(retrieval: RetrievalResult, *, note: str) -> GroundedAnswer:
    """Respuesta determinista $0: lista hechos y top fragmentos con sus citas."""
    parts: list[str] = []
    used: list[int] = []
    for f in retrieval.facts[:_MAX_EXTRACTIVE_FACTS]:
        parts.append(f"{f.src} {f.rel} {f.dst} [evento {f.evidence_event}]")
        used.append(f.evidence_event)
    for c in retrieval.chunks[:_MAX_EXTRACTIVE_CHUNKS]:
        parts.append(f"«{_snippet(c.text)}» [evento {c.event_id}]")
        used.append(c.event_id)
    body = "; ".join(parts) if parts else _DONT_KNOW
    answer = f"Según la memoria: {body}." if parts else _DONT_KNOW
    return GroundedAnswer(
        answer=answer,
        grounded=bool(parts),
        used_events=_dedupe(used),
        engine="extractive",
        note=note,
    )


def answer_from_retrieval(
    retrieval: RetrievalResult,
    *,
    inference: InferenceClient | None = None,
) -> GroundedAnswer:
    """Convierte el contexto recuperado en una respuesta citada (§8, §11.1).

    1. No `answerable` → "no sé" (engine="none", grounded=False).
    2. Con proveedor inyectado: pide un JSON `{answer, used_events}` al modelo con
       el prompt versionado (que le prohíbe usar conocimiento externo y le exige
       citar los eventos o decir que no sabe). engine="llm".
    3. Sin proveedor / proveedor sin configurar / salida inválida → respuesta
       extractiva determinista con las citas recuperadas. engine="extractive".

    El proveedor entra por inyección (seam de costo): por defecto `None` ⇒ camino
    extractivo, $0. Ningún camino llama a un proveedor real.
    """
    if not retrieval.answerable:
        return GroundedAnswer(
            answer=_DONT_KNOW,
            grounded=False,
            used_events=[],
            engine="none",
            note=retrieval.note,
        )

    context, context_events = _context_block(retrieval)

    if inference is None:
        return _extractive(retrieval, note=_EXTRACTIVE_NOTE)

    system, user_template = _load_prompt(PROMPT_VERSION)
    user = user_template.format(query=retrieval.query, context=context)
    try:
        data = inference.complete_json(system=system, user=user, purpose=_PURPOSE)
        parsed = _LLMAnswer.model_validate(data)
    except (ProviderNotConfigured, ValidationError):
        # Proveedor no configurado o salida no confiable: caemos a extractivo $0.
        return _extractive(retrieval, note=_EXTRACTIVE_FALLBACK_NOTE)

    # `used_events` del modelo se ancla a los eventos realmente presentes en el
    # contexto: no dejamos que invente citas fuera de la evidencia (§8).
    allowed = set(context_events)
    used = _dedupe([e for e in parsed.used_events if e in allowed])
    return GroundedAnswer(
        answer=parsed.answer,
        grounded=True,
        used_events=used,
        engine="llm",
        note=f"Respuesta generada por modelo ({PROMPT_VERSION}), anclada a la evidencia.",
    )
