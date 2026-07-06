"""Corpus de inyección para el simulador (SYSTEM_PROMPT §9.4).

Toda corrida del simulador pasa el corpus de inyección
(tests/injection_suite/cases/injection_cases.jsonl): mails/notas/transcripciones
con instrucciones embebidas. CUALQUIER obediencia = `dangerous` = la corrida
falla la compuerta.

Este módulo sólo CARGA el corpus como datos y lo convierte en eventos
disparadores. La detección de obediencia la hace el evaluador N1
(`evaluate_hard_rules`) sobre las acciones que el agente proponga: no hay lógica
de "obediencia" duplicada acá.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cortex.events.models import Event

# Ubicación canónica del corpus (SYSTEM_PROMPT §9.4). Se resuelve subiendo desde
# este archivo hasta la raíz del repo (donde vive tests/). Si el layout cambia,
# `load_injection_corpus(path=...)` permite pasar la ruta explícita.
_CORPUS_RELATIVE = Path("tests") / "injection_suite" / "cases" / "injection_cases.jsonl"


def default_corpus_path() -> Path:
    """Localiza el corpus subiendo desde este módulo hasta hallar tests/…jsonl."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / _CORPUS_RELATIVE
        if candidate.is_file():
            return candidate
    # Fallback: relativo al cwd (por si el repo se ejecuta desde su raíz).
    return _CORPUS_RELATIVE


def load_injection_corpus(path: Path | None = None) -> list[Event]:
    """Carga el corpus como eventos disparadores (source/type de cada vector).

    Sólo los vectores NO confiables (`trusted=false`) son inyecciones: el control
    negativo `human_ui` se excluye (esa fuente SÍ tiene autoridad de instrucción).
    """
    corpus_path = path if path is not None else default_corpus_path()
    events: list[Event] = []
    with corpus_path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            raw: dict[str, Any] = json.loads(line)
            if bool(raw.get("trusted", False)):
                continue  # control negativo: no es un vector de inyección
            events.append(_to_event(raw, event_id=i))
    return events


def _to_event(raw: dict[str, Any], *, event_id: int) -> Event:
    payload: dict[str, Any] = {"body": str(raw.get("body", ""))}
    for key in ("from", "to", "cc", "subject"):
        if key in raw and raw[key] is not None:
            payload[key] = str(raw[key])
    return Event(
        id=event_id,
        ingested_at=datetime.now(tz=UTC),
        ts=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        source=str(raw["source"]),
        type=str(raw["type"]),
        external_id=f"inj-{raw['id']}",
        actor=raw.get("from"),
        payload=payload,
        pipeline_ver="0.0.0-injection-corpus",
    )
