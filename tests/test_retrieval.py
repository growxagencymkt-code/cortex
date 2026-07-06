"""Tests de recuperación híbrida + chunks en el rebuild (F2). Costo $0."""

from __future__ import annotations

from datetime import UTC, datetime

from cortex.events.models import EventIn
from cortex.events.store import InMemoryEventStore
from cortex.memory.build import build_memory
from cortex.memory.retrieval import answer_query


def _store_with_mail() -> InMemoryEventStore:
    store = InMemoryEventStore()
    store.append(
        EventIn(
            ts=datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
            source="gmail",
            type="email.received",
            external_id="m-1",
            actor="Ana Lopez <ana@fenix.com>",
            payload={
                "from": "Ana Lopez <ana@fenix.com>",
                "to": "yo@ejemplo.com",
                "subject": "Presupuesto Fenix",
                "body": "Hola, te envío el presupuesto del proyecto Fenix para revisar.",
            },
            pipeline_ver="0.1.0-test",
        )
    )
    return store


def test_rebuild_builds_chunks() -> None:
    store = _store_with_mail()
    memory = build_memory(store)
    assert memory.stats.chunks_built >= 1
    assert memory.chunk_index.count() == memory.stats.chunks_built
    # cada chunk lleva embedding de la dimensión del embedder y su modelo
    chunk = memory.chunk_index.all_chunks()[0]
    assert len(chunk.embedding) == memory.embedder.dim
    assert chunk.embed_model == memory.embedder.model


def test_graph_hop_returns_facts_with_evidence() -> None:
    store = _store_with_mail()
    # "fenix.com" ancla la entidad org; debe traer la relación member_of con evidencia
    result = answer_query(store, "qué sabemos de fenix.com")
    assert result.answerable
    assert "fenix.com" in result.seeds
    assert any(f.rel == "member_of" and f.dst == "fenix.com" for f in result.facts)
    assert all(f.evidence_event > 0 for f in result.facts)  # principio 2


def test_semantic_hop_returns_chunks_with_provenance() -> None:
    store = _store_with_mail()
    result = answer_query(store, "presupuesto del proyecto")
    assert result.answerable
    assert result.chunks
    top = result.chunks[0]
    assert top.event_id == 1
    assert top.source == "gmail"
    assert top.ts is not None


def test_no_evidence_says_dont_know() -> None:
    store = _store_with_mail()
    result = answer_query(store, "xkcd qwerty zzzznope")
    assert result.answerable is False
    assert result.facts == []
    assert result.chunks == []
    assert "no sé" in result.note.lower() or "no se" in result.note.lower()


def test_retrieval_never_invents_beyond_evidence() -> None:
    # Toda respuesta fundamentada cita evidencia; sin evidencia, no responde.
    store = _store_with_mail()
    grounded = answer_query(store, "fenix.com presupuesto")
    for fact in grounded.facts:
        assert fact.evidence_event > 0
    for chunk in grounded.chunks:
        assert chunk.event_id > 0
