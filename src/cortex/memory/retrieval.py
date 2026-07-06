"""Recuperación híbrida (SYSTEM_PROMPT §8) — F2.

Dos saltos sobre la memoria:
1. **Salto de grafo:** resolver las entidades mencionadas en la consulta y
   expandir 1–2 niveles de relaciones vigentes a la fecha relevante. Cada hecho
   viaja con su `evidence_event` (principio 2).
2. **Salto semántico:** vector search sobre chunks FILTRADO por esas entidades
   (§6, GIN(entity_ids)) + una búsqueda global de menor peso.

Regla de oro (§8): **sin evidencia recuperada, el sistema dice que no sabe.**
Jamás rellena con conocimiento general. El contexto que arma incluye los hechos
del grafo (con evidencia) y los chunks (con fecha/fuente) + la instrucción de
citar evidencia. Este módulo NO genera lenguaje (eso es el núcleo cognitivo con
un proveedor); entrega el CONTEXTO fundamentado, costo $0.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cortex.events.models import Event
from cortex.events.store import EventStore
from cortex.memory.build import build_memory
from cortex.memory.chunks import InMemoryChunkIndex, ScoredChunk
from cortex.memory.embeddings import Embedder, build_embedder, tokenize
from cortex.memory.graph import InMemoryGraph

_MIN_SURFACE_LEN = 3  # evita seeds ruidosos por tokens muy cortos
_NO_EVIDENCE_NOTE = (
    "Sin evidencia recuperada en la memoria. No sé la respuesta: no relleno con "
    "conocimiento general (§8)."
)
_CITE_NOTE = (
    "Respondé SOLO con estos hechos (cada uno cita su evidence_event) y chunks "
    "(con fecha/fuente). Si no alcanzan, decí que no sabés. No inventes (§8)."
)


class RetrievedFact(BaseModel):
    """Un hecho del grafo recuperado, con su evidencia."""

    model_config = ConfigDict(frozen=True)

    src: str
    rel: str
    dst: str
    evidence_event: int
    valid_from: datetime


class RetrievedChunk(BaseModel):
    """Un fragmento del índice semántico recuperado, con su procedencia."""

    model_config = ConfigDict(frozen=True)

    text: str
    event_id: int
    source: str | None
    ts: datetime | None
    score: float


class RetrievalResult(BaseModel):
    """Contexto fundamentado para responder una consulta (§8)."""

    model_config = ConfigDict(frozen=True)

    query: str
    answerable: bool
    seeds: list[str] = Field(default_factory=list)
    facts: list[RetrievedFact] = Field(default_factory=list)
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    note: str = ""


def _seed_entities(graph: InMemoryGraph, query: str) -> list[UUID]:
    """Entidades cuyo nombre o alias aparece en la consulta (match léxico).

    Determinista y $0. La resolución de entidades de una consulta en lenguaje
    natural es en el fondo tarea del modelo; acá el baseline léxico da los puntos
    de entrada al grafo sin gastar.
    """
    q = query.casefold()
    seeds: list[UUID] = []
    for rec in graph.entities_all():
        surfaces = [rec.name, *rec.aliases]
        for surface in surfaces:
            s = surface.casefold()
            if len(s) >= _MIN_SURFACE_LEN and s in q:
                seeds.append(rec.id)
                break
    return seeds


def _facts_from_seeds(
    graph: InMemoryGraph, seeds: list[UUID], *, at: datetime, hops: int, max_facts: int
) -> list[RetrievedFact]:
    """Expande las relaciones vigentes a `at` de los seeds, hasta `hops` niveles.

    Considera relaciones en AMBAS direcciones (donde la entidad es `src` o `dst`):
    "de quién sé que es member_of de esta org" necesita la relación entrante. Cada
    hecho viaja con su `evidence_event` (principio 2).
    """
    valid = [
        r
        for r in graph.all_relations()
        if r.valid_from <= at and (r.valid_to is None or at < r.valid_to)
    ]
    facts: list[RetrievedFact] = []
    seen_rel_ids: set[int] = set()
    frontier: set[UUID] = set(seeds)
    visited: set[UUID] = set()
    for _ in range(max(1, hops)):
        current = frontier - visited
        if not current:
            break
        visited |= current
        next_frontier: set[UUID] = set()
        for rel in valid:
            if rel.id in seen_rel_ids:
                continue
            if rel.src not in current and rel.dst not in current:
                continue
            seen_rel_ids.add(rel.id)
            src_rec = graph.get_entity(rel.src)
            dst_rec = graph.get_entity(rel.dst)
            if src_rec is None or dst_rec is None:
                continue
            facts.append(
                RetrievedFact(
                    src=src_rec.name,
                    rel=rel.rel,
                    dst=dst_rec.name,
                    evidence_event=rel.evidence_event,
                    valid_from=rel.valid_from,
                )
            )
            next_frontier.add(rel.src)
            next_frontier.add(rel.dst)
            if len(facts) >= max_facts:
                return facts
        frontier = next_frontier
    return facts


def retrieve(
    query: str,
    *,
    graph: InMemoryGraph,
    chunk_index: InMemoryChunkIndex,
    embedder: Embedder,
    events_by_id: dict[int, Event],
    at: datetime | None = None,
    top_k: int = 5,
    hops: int = 2,
    max_facts: int = 20,
    min_global_score: float = 1e-6,
) -> RetrievalResult:
    """Recuperación híbrida (§8): salto de grafo + salto semántico, con evidencia.

    El salto semántico GLOBAL exige similitud estrictamente positiva
    (`min_global_score`): si la consulta no comparte vocabulario con ningún
    chunk (score 0) y no ancló ninguna entidad, el resultado es "no sé" (§8). El
    salto FILTRADO por entidades es permisivo: si el grafo dice que esas
    entidades importan, sus chunks entran como contexto aunque el score sea bajo.
    """
    when = at if at is not None else datetime.now(tz=UTC)
    seeds = _seed_entities(graph, query)
    seed_names = [r.name for sid in seeds if (r := graph.get_entity(sid)) is not None]

    facts = _facts_from_seeds(graph, seeds, at=when, hops=hops, max_facts=max_facts)

    query_vec = embedder.embed([query])[0] if chunk_index.count() else []
    scored: list[ScoredChunk] = []
    if query_vec:
        # Filtrado por entidades (anclado al grafo, permisivo) + global (exige
        # solapamiento real), dedupe por chunk id.
        by_id: dict[int, ScoredChunk] = {}
        if seeds:
            for sc in chunk_index.search(query_vec, top_k=top_k, entity_ids=seeds):
                by_id[sc.chunk.id] = sc
        # Anclaje léxico: con el embedder léxico (hashing), un chunk GLOBAL sólo
        # cuenta si comparte un token real con la consulta. Elimina el ruido por
        # colisión de hash (falsos "answerable"). Un embedder semántico real no
        # se filtra así (sinónimos no comparten token).
        query_tokens = {t for t in tokenize(query) if len(t) >= _MIN_SURFACE_LEN}
        for sc in chunk_index.search(query_vec, top_k=top_k, min_score=min_global_score):
            if sc.chunk.id in by_id:
                continue
            if embedder.is_lexical and not (query_tokens & set(tokenize(sc.chunk.text))):
                continue
            by_id[sc.chunk.id] = sc
        scored = sorted(by_id.values(), key=lambda s: (-s.score, s.chunk.id))[:top_k]

    chunks: list[RetrievedChunk] = []
    for sc in scored:
        ev = events_by_id.get(sc.chunk.event_id)
        chunks.append(
            RetrievedChunk(
                text=sc.chunk.text,
                event_id=sc.chunk.event_id,
                source=ev.source if ev is not None else None,
                ts=ev.ts if ev is not None else None,
                score=sc.score,
            )
        )

    answerable = bool(facts or chunks)
    return RetrievalResult(
        query=query,
        answerable=answerable,
        seeds=seed_names,
        facts=facts,
        chunks=chunks,
        note=_CITE_NOTE if answerable else _NO_EVIDENCE_NOTE,
    )


def answer_query(
    store: EventStore,
    query: str,
    *,
    embedder: Embedder | None = None,
    at: datetime | None = None,
    top_k: int = 5,
    hops: int = 2,
) -> RetrievalResult:
    """Reconstruye la memoria desde el log y recupera contexto para `query`.

    Conveniencia para CLI/API: build + retrieve con el MISMO embedder (para que
    las dimensiones coincidan). Costo $0 por defecto (Hashing + determinista).
    """
    emb = embedder if embedder is not None else build_embedder()
    memory = build_memory(store, embedder=emb)
    events_by_id = {ev.id: ev for ev in store.all_events()}
    return retrieve(
        query,
        graph=memory.graph,
        chunk_index=memory.chunk_index,
        embedder=emb,
        events_by_id=events_by_id,
        at=at,
        top_k=top_k,
        hops=hops,
    )
