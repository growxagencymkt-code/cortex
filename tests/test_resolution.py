"""Cascada de resolución/desambiguación de entidades (sección 7 paso 4)."""

from __future__ import annotations

from cortex.extraction.models import ExtractedEntity
from cortex.memory import (
    CONFIDENCE_THRESHOLD,
    DisambiguationQueue,
    EntityResolver,
    InMemoryGraph,
    NeedsDisambiguation,
    Resolved,
    Unresolved,
)


class FakeEmbedder:
    """Embedder determinista para tests ($0, sin proveedor real).

    Mapea textos conocidos a vectores fijos; todo lo demás a un vector nulo.
    """

    def __init__(self, mapping: dict[str, list[float]]) -> None:
        self._mapping = mapping

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._mapping.get(t, [0.0, 0.0]) for t in texts]


def _person(name: str, mention: str = "") -> ExtractedEntity:
    return ExtractedEntity(kind="person", name=name, mention=mention)


def test_threshold_constant_matches_spec() -> None:
    assert CONFIDENCE_THRESHOLD == 0.8


def test_exact_name_match_resolves_full_confidence() -> None:
    g = InMemoryGraph()
    juan = g.upsert_entity("person", "Juan Perez", first_seen_event=1)
    res = EntityResolver(g).resolve(_person("juan perez"))  # case-insensitive
    assert isinstance(res, Resolved)
    assert res.entity_id == juan.id
    assert res.confidence == 1.0


def test_alias_match_resolves_high_confidence() -> None:
    g = InMemoryGraph()
    juan = g.upsert_entity("person", "Juan Perez", aliases=["JP"], first_seen_event=1)
    res = EntityResolver(g).resolve(_person("jp"))
    assert isinstance(res, Resolved)
    assert res.entity_id == juan.id
    assert 0.8 <= res.confidence < 1.0


def test_no_match_no_embedder_is_unresolved_and_readonly() -> None:
    g = InMemoryGraph()
    g.upsert_entity("person", "Juan Perez", first_seen_event=1)
    res = EntityResolver(g).resolve(_person("Desconocida"))
    assert isinstance(res, Unresolved)
    assert res.extracted.name == "Desconocida"
    # resolve() NO escribe: sigue habiendo una sola entidad.
    assert len(g.entities_by_kind("person")) == 1


def test_embedder_below_threshold_needs_disambiguation() -> None:
    g = InMemoryGraph()
    juan = g.upsert_entity("person", "Juan Perez", first_seen_event=1)
    # query ortogonal al candidato → cosine 0.0 < 0.8.
    emb = FakeEmbedder({"Juancito": [1.0, 0.0], "Juan Perez": [0.0, 1.0]})
    res = EntityResolver(g, embedder=emb).resolve(_person("Juancito"))
    assert isinstance(res, NeedsDisambiguation)
    assert res.candidates == [juan.id]
    assert res.extracted.name == "Juancito"
    # sigue sin escribir.
    assert len(g.entities_by_kind("person")) == 1


def test_embedder_above_threshold_resolves() -> None:
    g = InMemoryGraph()
    juan = g.upsert_entity("person", "Juan Perez", first_seen_event=1)
    # query colineal al candidato → cosine 1.0 >= 0.8.
    emb = FakeEmbedder({"Juancito": [1.0, 0.0], "Juan Perez": [1.0, 0.0]})
    res = EntityResolver(g, embedder=emb).resolve(_person("Juancito"))
    assert isinstance(res, Resolved)
    assert res.entity_id == juan.id
    assert res.confidence >= CONFIDENCE_THRESHOLD


def test_embedder_ignored_when_no_candidates_of_kind() -> None:
    # sin candidatos del kind, ni se llama al embedder: entidad nueva.
    g = InMemoryGraph()
    g.upsert_entity("org", "Acme", first_seen_event=1)
    emb = FakeEmbedder({})
    res = EntityResolver(g, embedder=emb).resolve(_person("Alguien"))
    assert isinstance(res, Unresolved)


# ------------------------------------------------------------- bandeja (sección 11.2)
def test_disambiguation_queue_enqueue_and_pending() -> None:
    g = InMemoryGraph()
    q = DisambiguationQueue(g)
    assert q.pending() == []
    item = NeedsDisambiguation(question="¿quién?", candidates=[], extracted=_person("X"))
    q.enqueue(item)
    assert q.pending() == [item]
    # pending() devuelve una copia: mutarla no afecta la bandeja.
    q.pending().clear()
    assert len(q.pending()) == 1


def test_answering_feeds_alias_into_chosen_entity() -> None:
    g = InMemoryGraph()
    juan = g.upsert_entity("person", "Juan Perez", first_seen_event=1)
    q = DisambiguationQueue(g)

    extracted = _person("Juanci", mention="Juanci P.")
    item = NeedsDisambiguation(
        question="¿'Juanci' es Juan Perez?", candidates=[juan.id], extracted=extracted
    )
    q.enqueue(item)

    # antes de responder, el alias no resuelve.
    assert g.find_by_name_or_alias("person", "Juanci") is None

    updated = q.resolve_answer("¿'Juanci' es Juan Perez?", juan.id)
    assert updated.id == juan.id
    # la forma de superficie quedó como alias de la entidad elegida.
    assert "Juanci" in updated.aliases
    assert "Juanci P." in updated.aliases
    assert g.find_by_name_or_alias("person", "Juanci") is juan
    # y salió de la bandeja.
    assert q.pending() == []


def test_resolve_answer_unknown_question_or_entity_raises() -> None:
    import uuid

    import pytest

    g = InMemoryGraph()
    juan = g.upsert_entity("person", "Juan Perez", first_seen_event=1)
    q = DisambiguationQueue(g)
    q.enqueue(
        NeedsDisambiguation(question="q", candidates=[juan.id], extracted=_person("X"))
    )
    with pytest.raises(ValueError):
        q.resolve_answer("pregunta inexistente", juan.id)
    with pytest.raises(ValueError):
        q.resolve_answer("q", uuid.uuid4())


def test_end_to_end_resolve_then_disambiguate() -> None:
    # Flujo típico: resolver da NeedsDisambiguation → a la bandeja → respuesta
    # alimenta alias → una segunda resolución del mismo texto ya matchea por alias.
    g = InMemoryGraph()
    juan = g.upsert_entity("person", "Juan Perez", first_seen_event=1)
    emb = FakeEmbedder({"Juanci": [1.0, 0.0], "Juan Perez": [0.0, 1.0]})
    resolver = EntityResolver(g, embedder=emb)
    q = DisambiguationQueue(g)

    first = resolver.resolve(_person("Juanci"))
    assert isinstance(first, NeedsDisambiguation)
    q.enqueue(first)
    q.resolve_answer(first.question, juan.id)

    second = resolver.resolve(_person("Juanci"))
    assert isinstance(second, Resolved)
    assert second.entity_id == juan.id
