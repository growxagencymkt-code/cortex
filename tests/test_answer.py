"""Tests de generación de respuesta fundamentada (§8, §11.1). Costo $0.

Fixtures de `RetrievalResult` armadas a mano (no hace falta un store). El camino
LLM se ejercita con `StaticInferenceClient` (respuestas fijas, sin proveedor real).
"""

from __future__ import annotations

from datetime import UTC, datetime

from cortex.extraction.inference import (
    StaticInferenceClient,
    UnconfiguredInferenceClient,
)
from cortex.memory.answer import (
    PROMPT_VERSION,
    GroundedAnswer,
    _load_prompt,
    answer_from_retrieval,
)
from cortex.memory.retrieval import RetrievalResult, RetrievedChunk, RetrievedFact

_TS = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


def _answerable() -> RetrievalResult:
    return RetrievalResult(
        query="qué sabemos de fenix.com",
        answerable=True,
        seeds=["fenix.com"],
        facts=[
            RetrievedFact(
                src="Ana Lopez",
                rel="member_of",
                dst="fenix.com",
                evidence_event=1,
                valid_from=_TS,
            )
        ],
        chunks=[
            RetrievedChunk(
                text="te envío el presupuesto del proyecto Fenix para revisar",
                event_id=1,
                source="gmail",
                ts=_TS,
                score=0.42,
            )
        ],
        note="Respondé SOLO con estos hechos y chunks.",
    )


def _unanswerable() -> RetrievalResult:
    return RetrievalResult(
        query="cuál es la capital de Marte",
        answerable=False,
        note="Sin evidencia recuperada en la memoria. No sé la respuesta (§8).",
    )


def test_unanswerable_says_dont_know() -> None:
    result = answer_from_retrieval(_unanswerable())
    assert isinstance(result, GroundedAnswer)
    assert result.grounded is False
    assert result.engine == "none"
    assert result.used_events == []
    assert "no sé" in result.answer.casefold()
    # el don't-know propaga la nota de la recuperación
    assert result.note == _unanswerable().note


def test_llm_path_parses_static_response() -> None:
    inference = StaticInferenceClient(
        {"answer:v1": {"answer": "Ana Lopez es miembro de fenix.com [evento 1].", "used_events": [1]}}
    )
    result = answer_from_retrieval(_answerable(), inference=inference)
    assert result.engine == "llm"
    assert result.grounded is True
    assert result.used_events == [1]
    assert result.answer == "Ana Lopez es miembro de fenix.com [evento 1]."


def test_llm_drops_uncited_events_outside_evidence() -> None:
    # el modelo "cita" un evento 99 que no está en la evidencia → se descarta (§8)
    inference = StaticInferenceClient(
        {"answer:v1": {"answer": "…", "used_events": [1, 99]}}
    )
    result = answer_from_retrieval(_answerable(), inference=inference)
    assert result.engine == "llm"
    assert result.used_events == [1]


def test_none_inference_is_extractive_and_grounded() -> None:
    result = answer_from_retrieval(_answerable(), inference=None)
    assert result.engine == "extractive"
    assert result.grounded is True
    assert result.used_events == [1]
    # menciona un hecho/chunk y un número de evento
    assert "evento 1" in result.answer
    assert "member_of" in result.answer or "Fenix" in result.answer


def test_unconfigured_provider_falls_through_to_extractive() -> None:
    result = answer_from_retrieval(_answerable(), inference=UnconfiguredInferenceClient())
    assert result.engine == "extractive"
    assert result.grounded is True
    assert "evento 1" in result.answer


def test_invalid_llm_output_falls_through_to_extractive() -> None:
    # falta el campo obligatorio `answer` → ValidationError → extractivo $0
    inference = StaticInferenceClient({"answer:v1": {"used_events": [1]}})
    result = answer_from_retrieval(_answerable(), inference=inference)
    assert result.engine == "extractive"
    assert result.grounded is True


def test_prompt_file_exists_and_loads() -> None:
    system, user_template = _load_prompt(PROMPT_VERSION)
    assert system
    assert "{query}" in user_template
    assert "{context}" in user_template
    # el system prohíbe conocimiento externo y exige citar eventos (§8)
    assert "evento" in system.casefold()
