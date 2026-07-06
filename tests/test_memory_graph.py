"""Grafo de entidades/relaciones con evidencia (sección 6 + sección 7 pasos 4-5)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cortex.memory import EntityRecord, InMemoryGraph, RelationRecord


def _t(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 7, day, hour, 0, tzinfo=UTC)


# --------------------------------------------------------------- entities / UNIQUE
def test_upsert_unique_kind_name_merges_aliases_and_keeps_earliest_first_seen() -> None:
    g = InMemoryGraph()
    e1 = g.upsert_entity("person", "Juan Perez", aliases=["Juan"], first_seen_event=5)
    e2 = g.upsert_entity(
        "person", "Juan Perez", aliases=["Juan", "JP", "Juanci"], first_seen_event=2
    )

    # UNIQUE(kind,name): una sola entidad, misma identidad.
    assert e1.id == e2.id
    assert len(g.entities_by_kind("person")) == 1
    # aliases mergeados, deduplicados, orden estable.
    assert e2.aliases == ["Juan", "JP", "Juanci"]
    # first_seen_event: el más temprano.
    assert e2.first_seen_event == 2


def test_upsert_different_name_is_a_different_entity() -> None:
    g = InMemoryGraph()
    a = g.upsert_entity("person", "Ana", first_seen_event=1)
    b = g.upsert_entity("person", "Beto", first_seen_event=1)
    assert a.id != b.id
    assert len(g.entities_by_kind("person")) == 2


def test_same_name_different_kind_are_distinct() -> None:
    g = InMemoryGraph()
    p = g.upsert_entity("person", "Acme", first_seen_event=1)
    o = g.upsert_entity("org", "Acme", first_seen_event=1)
    assert p.id != o.id


def test_find_by_name_or_alias_is_case_insensitive() -> None:
    g = InMemoryGraph()
    e = g.upsert_entity("person", "Juan Perez", aliases=["JP"], first_seen_event=1)
    assert g.find_by_name_or_alias("person", "juan perez") is e
    assert g.find_by_name_or_alias("person", "jp") is e
    assert g.find_by_name_or_alias("person", "desconocido") is None
    # el kind importa: no cruza tipos.
    assert g.find_by_name_or_alias("org", "Juan Perez") is None


def test_get_entity_roundtrip() -> None:
    g = InMemoryGraph()
    e = g.upsert_entity("org", "Acme", first_seen_event=1)
    assert g.get_entity(e.id) is e
    import uuid

    assert g.get_entity(uuid.uuid4()) is None


def test_deterministic_entity_id_across_graphs() -> None:
    # Misma (kind,name) → mismo UUID en grafos independientes (reproducibilidad).
    a = InMemoryGraph().upsert_entity("person", "Ana", first_seen_event=1)
    b = InMemoryGraph().upsert_entity("person", "Ana", first_seen_event=9)
    assert a.id == b.id


# -------------------------------------------------------- relations / evidence rule
def test_add_relation_requires_positive_evidence_event() -> None:
    g = InMemoryGraph()
    a = g.upsert_entity("person", "Ana", first_seen_event=1)
    o = g.upsert_entity("org", "Acme", first_seen_event=1)
    for bad in (0, -1, None):
        with pytest.raises(ValueError):
            g.add_relation(
                a.id, "works_at", o.id, evidence_event=bad, valid_from=_t(1)
            )
    # ninguna relación inválida quedó escrita.
    assert g.all_relations() == []


def test_add_relation_with_unknown_src_or_dst_raises() -> None:
    import uuid

    g = InMemoryGraph()
    a = g.upsert_entity("person", "Ana", first_seen_event=1)
    ghost = uuid.uuid4()
    with pytest.raises(ValueError):
        g.add_relation(ghost, "works_at", a.id, evidence_event=1, valid_from=_t(1))
    with pytest.raises(ValueError):
        g.add_relation(a.id, "works_at", ghost, evidence_event=1, valid_from=_t(1))


def test_add_relation_ids_are_monotonic() -> None:
    g = InMemoryGraph()
    a = g.upsert_entity("person", "Ana", first_seen_event=1)
    o = g.upsert_entity("org", "Acme", first_seen_event=1)
    r1 = g.add_relation(a.id, "member_of", o.id, evidence_event=1, valid_from=_t(1))
    r2 = g.add_relation(a.id, "emailed", o.id, evidence_event=2, valid_from=_t(2))
    assert (r1.id, r2.id) == (1, 2)


# ------------------------------------------------------------- contradiction (step 5)
def test_exclusive_relation_closes_prior_and_opens_new() -> None:
    g = InMemoryGraph(exclusive_rels=frozenset({"works_at"}))
    ana = g.upsert_entity("person", "Ana", first_seen_event=1)
    acme = g.upsert_entity("org", "Acme", first_seen_event=1)
    globex = g.upsert_entity("org", "Globex", first_seen_event=1)

    old = g.add_relation(ana.id, "works_at", acme.id, evidence_event=1, valid_from=_t(1))
    new = g.add_relation(ana.id, "works_at", globex.id, evidence_event=2, valid_from=_t(10))

    # la vigente anterior se cerró exactamente en el valid_from de la nueva.
    assert old.valid_to == _t(10)
    assert new.valid_to is None

    # temporalidad: antes ve la vieja, en/después ve la nueva.
    before = g.relations_valid_at(ana.id, _t(5))
    assert [r.dst for r in before] == [acme.id]
    at_switch = g.relations_valid_at(ana.id, _t(10))
    assert [r.dst for r in at_switch] == [globex.id]
    after = g.relations_valid_at(ana.id, _t(20))
    assert [r.dst for r in after] == [globex.id]

    # nada se borró: la historia completa sigue.
    assert len(g.all_relations()) == 2


def test_non_exclusive_relations_coexist() -> None:
    g = InMemoryGraph(exclusive_rels=frozenset({"works_at"}))
    ana = g.upsert_entity("person", "Ana", first_seen_event=1)
    p1 = g.upsert_entity("project", "P1", first_seen_event=1)
    p2 = g.upsert_entity("project", "P2", first_seen_event=1)

    g.add_relation(ana.id, "works_on", p1.id, evidence_event=1, valid_from=_t(1))
    g.add_relation(ana.id, "works_on", p2.id, evidence_event=2, valid_from=_t(2))

    valid = g.relations_valid_at(ana.id, _t(5))
    assert {r.dst for r in valid} == {p1.id, p2.id}
    # ninguna se cerró.
    assert all(r.valid_to is None for r in g.all_relations())


def test_relations_valid_at_temporal_boundaries() -> None:
    g = InMemoryGraph(exclusive_rels=frozenset({"status"}))
    task = g.upsert_entity("topic", "tarea", first_seen_event=1)
    open_ = g.upsert_entity("topic", "open", first_seen_event=1)
    done = g.upsert_entity("topic", "done", first_seen_event=1)

    g.add_relation(task.id, "status", open_.id, evidence_event=1, valid_from=_t(1))
    g.add_relation(task.id, "status", done.id, evidence_event=2, valid_from=_t(10))

    # justo antes del cierre: solo 'open' (valid_from<=at, at<valid_to).
    assert [r.dst for r in g.relations_valid_at(task.id, _t(9, 23))] == [open_.id]
    # límite inferior inclusivo: en valid_from (día 1, 12:00) ya vale.
    assert [r.dst for r in g.relations_valid_at(task.id, _t(1))] == [open_.id]
    # justo antes de valid_from (día 1, 00:00) todavía no existe: vacío.
    assert g.relations_valid_at(task.id, _t(1, 0)) == []
    assert g.relations_valid_at(task.id, datetime(2026, 6, 30, tzinfo=UTC)) == []


def test_record_types_are_the_public_api() -> None:
    # Sanity: los tipos exportados son los que devuelve el grafo.
    g = InMemoryGraph()
    e = g.upsert_entity("person", "Ana", first_seen_event=1)
    o = g.upsert_entity("org", "Acme", first_seen_event=1)
    r = g.add_relation(e.id, "member_of", o.id, evidence_event=1, valid_from=_t(1))
    assert isinstance(e, EntityRecord)
    assert isinstance(r, RelationRecord)
