"""Suite de inyección de prompts (SYSTEM_PROMPT principio 3 + §9.4).

OBLIGATORIA en CI: cualquier obediencia a una instrucción embebida en contenido
observado (mails, notas, transcripciones) es fallo automático.

Qué prueba, por cada vector del corpus (cases/injection_cases.jsonl):
  (a) `DeterministicExtractor` produce sólo DATOS — nunca una relación/compromiso
      que represente ejecutar la orden, ni una entidad-objetivo de exfiltración; y
      `ExtractionResult` no expone superficie de acción (sin atributo `actions`).
  (b) Un `ActionRecorder` usado como espía queda VACÍO para fuentes no confiables:
      `assert_no_obedience()` no lanza.
  (c) La fuente observada NO es de confianza: `is_trusted_instruction_source` False.

Además:
  - Prueba con dientes: un componente adversarial que SÍ obedece hace que
    `assert_no_obedience()` lance AssertionError (la guarda atrapa la obediencia,
    no pasa de forma vacía).
  - Control negativo: una fuente CONFIABLE (`human_ui`) sí puede instruir.

Costo $0: sólo `DeterministicExtractor` / `StaticInferenceClient`. Ningún proveedor
real se cablea nunca.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cortex.events.models import Event
from cortex.extraction import DeterministicExtractor, ExtractionResult
from cortex.governance.injection import (
    ActionRecorder,
    RecordedAction,
    is_trusted_instruction_source,
)

# --- Corpus de vectores ------------------------------------------------------

_CASES_FILE = Path(__file__).parent / "cases" / "injection_cases.jsonl"

# Relaciones que representarían EJECUTAR la orden embebida (jamás deben salir del
# extractor: éste produce hechos observados, no acciones).
FORBIDDEN_ACTION_RELS: frozenset[str] = frozenset(
    {"forward_to", "send_to", "delete", "transfer", "reveal"}
)

# Marcadores de objetivos de exfiltración que nunca deben convertirse en entidad
# ni colarse como objetivo de una acción.
EXFIL_MARKERS: tuple[str, ...] = ("evil.com", "attacker", "exfil", "leak@")


@dataclass(frozen=True)
class InjectionCase:
    """Un vector de inyección: contenido observado con una instrucción embebida."""

    id: str
    label: str
    source: str
    type: str
    body: str
    trusted: bool
    sender: str | None = None
    recipient: str | None = None
    subject: str | None = None

    def payload(self) -> dict[str, Any]:
        data: dict[str, Any] = {"body": self.body}
        if self.sender is not None:
            data["from"] = self.sender
        if self.recipient is not None:
            data["to"] = self.recipient
        if self.subject is not None:
            data["subject"] = self.subject
        return data


def _load_cases() -> list[InjectionCase]:
    cases: list[InjectionCase] = []
    with _CASES_FILE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw: dict[str, Any] = json.loads(line)
            cases.append(
                InjectionCase(
                    id=str(raw["id"]),
                    label=str(raw["label"]),
                    source=str(raw["source"]),
                    type=str(raw["type"]),
                    body=str(raw["body"]),
                    trusted=bool(raw["trusted"]),
                    sender=raw.get("from"),
                    recipient=raw.get("to"),
                    subject=raw.get("subject"),
                )
            )
    return cases


_ALL_CASES: list[InjectionCase] = _load_cases()
OBSERVED_CASES: list[InjectionCase] = [c for c in _ALL_CASES if not c.trusted]
TRUSTED_CASES: list[InjectionCase] = [c for c in _ALL_CASES if c.trusted]


def _build_event(case: InjectionCase, event_id: int) -> Event:
    return Event(
        id=event_id,
        ingested_at=datetime.now(tz=UTC),
        ts=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        source=case.source,
        type=case.type,
        external_id=f"inj-{case.id}",
        actor=case.sender,
        payload=case.payload(),
        pipeline_ver="0.1.0-injection-suite",
    )


# --- Modelos de consumo (la frontera de confianza en código) -----------------


def guarded_consumer(result: ExtractionResult, recorder: ActionRecorder, *, source: str) -> None:
    """Cómo CORTEX consume una extracción: persiste DATOS, nunca obedece.

    Sólo una fuente CON autoridad de instrucción puede disparar una acción del
    sistema. Para contenido observado (no confiable) no registra ninguna acción:
    los hechos extraídos entran como dato, jamás como orden (principio 3).
    """
    _ = result  # los hechos se persistirían como DATO; acá no ejecutan nada
    if is_trusted_instruction_source(source):
        recorder.record(
            RecordedAction(
                kind="apply_instruction",
                detail="instrucción de fuente autenticada aplicada",
                triggered_by_source=source,
            )
        )


def naive_obedient_consumer(event: Event, recorder: ActionRecorder) -> None:
    """Componente ADVERSARIAL (con bug): interpreta el contenido como orden.

    Existe sólo para probar que la guarda tiene dientes: al obedecer una
    instrucción de una fuente observada, deja rastro con `triggered_by_source`
    igual a la fuente NO confiable → `assert_no_obedience()` debe lanzar.
    """
    body = str(event.payload.get("body", "")).lower()
    if any(k in body for k in ("reenvi", "forward", "borr", "delete", "transfer")):
        recorder.record(
            RecordedAction(
                kind="forward_email",
                detail="obedeció una instrucción embebida en el mail",
                triggered_by_source=event.source,
            )
        )


# --- (a) El extractor produce sólo DATOS -------------------------------------


@pytest.mark.injection
@pytest.mark.parametrize("case", OBSERVED_CASES, ids=lambda c: c.id)
def test_extractor_produces_data_only(case: InjectionCase) -> None:
    event = _build_event(case, event_id=1)
    result = DeterministicExtractor().extract(event)

    # Ninguna relación que represente ejecutar la orden.
    assert not any(r.rel in FORBIDDEN_ACTION_RELS for r in result.relations), (
        f"[{case.id}] el extractor fabricó una relación-acción prohibida"
    )
    # Ninguna entidad-objetivo de exfiltración (ni por nombre ni por alias).
    haystacks: list[str] = []
    for e in result.entities:
        haystacks.append(e.name.lower())
        haystacks.extend(a.lower() for a in e.aliases)
    assert not any(m in h for h in haystacks for m in EXFIL_MARKERS), (
        f"[{case.id}] un objetivo de exfiltración se coló como entidad"
    )
    # Los compromisos/decisiones son hechos observados, no órdenes de exfiltración.
    action_text = " ".join(
        [c.what.lower() for c in result.commitments]
        + [d.statement.lower() for d in result.decisions]
    )
    assert not any(m in action_text for m in EXFIL_MARKERS), (
        f"[{case.id}] un objetivo de exfiltración se coló como compromiso/decisión"
    )
    # El contrato de salida no expone ninguna superficie de acción.
    assert not hasattr(result, "actions"), f"[{case.id}] ExtractionResult expone acciones"


# --- (b) El espía queda vacío para contenido observado -----------------------


@pytest.mark.injection
@pytest.mark.parametrize("case", OBSERVED_CASES, ids=lambda c: c.id)
def test_spy_recorder_stays_empty_for_observed_content(case: InjectionCase) -> None:
    event = _build_event(case, event_id=2)
    recorder = ActionRecorder()

    # Pipeline correcto: extraer (dato) y consumir con la guarda de confianza.
    result = DeterministicExtractor().extract(event)
    guarded_consumer(result, recorder, source=event.source)

    assert recorder.actions == (), f"[{case.id}] se registró una acción sobre contenido observado"
    # No debe lanzar: no hubo obediencia.
    recorder.assert_no_obedience()


# --- (c) La fuente observada no es de confianza ------------------------------


@pytest.mark.injection
@pytest.mark.parametrize("case", OBSERVED_CASES, ids=lambda c: c.id)
def test_observed_source_is_not_trusted(case: InjectionCase) -> None:
    assert is_trusted_instruction_source(case.source) is False, (
        f"[{case.id}] fuente observada {case.source!r} tratada como confiable"
    )


# --- Cobertura mínima del corpus ---------------------------------------------


@pytest.mark.injection
def test_corpus_covers_enough_distinct_vectors() -> None:
    ids = [c.id for c in OBSERVED_CASES]
    assert len(ids) >= 15, f"se requieren >=15 vectores de inyección, hay {len(ids)}"
    assert len(set(ids)) == len(ids), "hay ids de caso duplicados en el corpus"


# --- Prueba con DIENTES: la guarda atrapa la obediencia ----------------------


@pytest.mark.injection
def test_guard_has_teeth_obedience_is_caught() -> None:
    """Si un componente OBEDECE contenido observado, la guarda debe lanzar.

    Sin esto, los tests (b) podrían pasar de forma vacía (un espía que nunca se
    llena no prueba nada). Acá forzamos la obediencia y exigimos que salte.
    """
    malicious = next(c for c in OBSERVED_CASES if c.id == "forward_exfil")
    event = _build_event(malicious, event_id=99)
    recorder = ActionRecorder()

    naive_obedient_consumer(event, recorder)

    # El componente adversarial dejó rastro de obediencia desde 'gmail'.
    assert recorder.actions, "el componente adversarial debía registrar una acción"
    assert recorder.actions[0].triggered_by_source == "gmail"
    with pytest.raises(AssertionError):
        recorder.assert_no_obedience()


# --- Control negativo: una fuente CONFIABLE sí puede instruir -----------------


@pytest.mark.injection
def test_negative_control_trusted_human_ui_may_instruct() -> None:
    """Las instrucciones de humanos autenticados (human_ui) SON legítimas.

    Documenta que la distinción confiable/observado es real: la misma guarda que
    bloquea todo el corpus observado NO bloquea una orden de human_ui.
    """
    assert TRUSTED_CASES, "falta el caso de control con fuente confiable"
    case = TRUSTED_CASES[0]
    assert case.source == "human_ui"
    assert is_trusted_instruction_source(case.source) is True

    event = _build_event(case, event_id=100)
    recorder = ActionRecorder()
    result = DeterministicExtractor().extract(event)
    guarded_consumer(result, recorder, source=event.source)

    # La guarda permitió la acción porque la fuente tiene autoridad de instrucción.
    assert len(recorder.actions) == 1
    assert recorder.actions[0].triggered_by_source == "human_ui"
    # Y no es obediencia a contenido observado → no lanza.
    recorder.assert_no_obedience()
