"""F1 de punta a punta: log → extracción → resolución → grafo con evidencia.

Verifica el criterio nuclear (principio 2): TODA relación lleva `evidence_event`
apuntando a un evento real del log. Y la forma de la aceptación F1: "¿qué
compromisos vencen esta semana?" se responde desde el grafo con evidencia.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cortex.connectors.base import ingest
from cortex.connectors.fixture import FixtureMailConnector
from cortex.events.store import InMemoryEventStore
from cortex.memory.build import build_memory, commitments_due_between

_CORPUS = Path(__file__).parent / "fixtures" / "sample_emails.jsonl"


def _store_with_corpus() -> InMemoryEventStore:
    store = InMemoryEventStore()
    ingest(FixtureMailConnector(_CORPUS), store, pipeline_ver="0.1.0-test")
    return store


def test_every_relation_carries_evidence_event() -> None:
    store = _store_with_corpus()
    valid_event_ids = {e.id for e in store.all_events()}

    result = build_memory(store)
    relations = result.graph.all_relations()

    assert relations, "el grafo debería tener relaciones"
    for r in relations:
        # Principio 2: sin evidencia no entra a la memoria.
        assert r.evidence_event > 0
        assert r.evidence_event in valid_event_ids


def test_graph_has_people_orgs_and_commitments() -> None:
    store = _store_with_corpus()
    result = build_memory(store)
    g = result.graph

    people = {e.name for e in g.entities_by_kind("person")}
    orgs = {e.name for e in g.entities_by_kind("org")}
    assert {"lucia@acme.com", "diego@northwind.io", "marta@globex.com"} <= people
    assert {"acme.com", "northwind.io", "globex.com"} <= orgs

    rel_types = {r.rel for r in g.all_relations()}
    assert {"emailed", "member_of", "committed"} <= rel_types
    assert g.entities_by_kind("commitment"), "debería haber compromisos materializados"


def test_commitments_due_this_week_query() -> None:
    """Aceptación F1 (forma): compromisos que vencen en una ventana, con evidencia."""
    store = _store_with_corpus()
    result = build_memory(store)
    g = result.graph

    # Semana del 6 al 12 de julio 2026: vencen los del 07/07 y 08/07 del corpus.
    start = datetime(2026, 7, 6, tzinfo=UTC)
    end = datetime(2026, 7, 12, tzinfo=UTC)
    due_ids = commitments_due_between(g, start, end)

    assert len(due_ids) >= 2
    for cid in due_ids:
        rec = g.get_entity(cid)
        assert rec is not None
        due = rec.attrs.get("due")
        assert isinstance(due, str) and "2026-07-0" in due
        # Cada compromiso tiene evidencia: una relación committed que lo respalda.
        backing = [r for r in g.all_relations() if r.dst == cid and r.rel == "committed"]
        assert backing and all(r.evidence_event > 0 for r in backing)


def test_build_is_deterministic() -> None:
    store = _store_with_corpus()
    a = build_memory(store).stats
    b = build_memory(store).stats
    assert (a.entities_built, a.relations_built, a.commitments_built) == (
        b.entities_built, b.relations_built, b.commitments_built,
    )


def test_entities_deduplicate_across_events() -> None:
    """El mismo remitente en varios mails es UNA entidad (resolución exacta)."""
    store = _store_with_corpus()
    result = build_memory(store)
    lucia = [e for e in result.graph.entities_by_kind("person") if e.name == "lucia@acme.com"]
    assert len(lucia) == 1  # aparece en s-001, s-004, s-007, s-010 → una sola entidad
