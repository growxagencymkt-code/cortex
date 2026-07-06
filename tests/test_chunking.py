"""Tests de chunking + índice de chunks (F2). Costo $0."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from cortex.events.models import Event
from cortex.memory.chunking import chunk_text, chunks_for_event, event_text
from cortex.memory.chunks import InMemoryChunkIndex


def _event(payload: dict[str, object]) -> Event:
    return Event(
        id=1,
        ts=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        ingested_at=datetime.now(tz=UTC),
        source="gmail",
        type="email.received",
        external_id="c-1",
        actor="a@x.com",
        payload=payload,
        pipeline_ver="0.1.0-test",
    )


def test_chunk_text_empty_returns_empty() -> None:
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_text_short_is_single_chunk() -> None:
    assert chunk_text("hola mundo", target_tokens=400) == ["hola mundo"]


def test_chunk_text_splits_with_overlap() -> None:
    words = " ".join(f"w{i}" for i in range(100))
    chunks = chunk_text(words, target_tokens=40, overlap_tokens=10)
    assert len(chunks) >= 2
    # solapamiento: el final del chunk 0 reaparece al inicio del chunk 1
    first_tail = chunks[0].split()[-10:]
    second_head = chunks[1].split()[:10]
    assert first_tail == second_head


def test_event_text_prefers_known_fields() -> None:
    txt = event_text(_event({"subject": "Presupuesto", "body": "detalle del presupuesto"}))
    assert "Presupuesto" in txt and "detalle" in txt


def test_chunks_for_event_produces_chunks() -> None:
    body = " ".join(f"palabra{i}" for i in range(50))
    chunks = chunks_for_event(_event({"subject": "S", "body": body}), target_tokens=20, overlap_tokens=5)
    assert len(chunks) >= 2


def test_chunk_index_search_filters_by_entity_and_ranks() -> None:
    idx = InMemoryChunkIndex()
    e1, e2 = uuid4(), uuid4()
    idx.add(event_id=1, text="alfa", embedding=[1.0, 0.0, 0.0], embed_model="m", entity_ids=[e1])
    idx.add(event_id=2, text="beta", embedding=[0.0, 1.0, 0.0], embed_model="m", entity_ids=[e2])
    idx.add(event_id=3, text="gamma", embedding=[0.9, 0.1, 0.0], embed_model="m", entity_ids=[e1])

    # búsqueda global: alfa (id1) es el más parecido a [1,0,0]
    top = idx.search([1.0, 0.0, 0.0], top_k=2)
    assert top[0].chunk.event_id == 1
    assert top[0].score >= top[1].score

    # filtrada por e2: sólo el chunk beta es candidato
    only_e2 = idx.search([1.0, 0.0, 0.0], entity_ids=[e2])
    assert len(only_e2) == 1 and only_e2[0].chunk.event_id == 2
