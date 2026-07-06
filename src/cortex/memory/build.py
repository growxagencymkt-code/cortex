"""Construcción de la memoria de grafo desde el log (pipeline §7, pasos 3-5).

Une las piezas de F1: por cada evento del log
  3. se extraen hechos estructurados (extractor),
  4. se resuelven las entidades contra el grafo (exacto→alias→embedding→
     desambiguación); las de baja confianza van a la bandeja, no se escriben,
  5. se escriben al grafo entidades y relaciones, cada una con `evidence_event`
     = id del evento que la respalda (principio 2).

Es la operación que `rebuild --from-events` ejecuta sobre TODO el log para
reconstruir la vista de grafo (principio 1). Determinista: mismo log → mismo
grafo. No muta el log jamás (sólo lee).

Los compromisos se materializan como hechos con evidencia: una entidad
`commitment` (con qué/cuándo/dirección en attrs) y una relación
`(persona)-[committed]->(commitment)`. Así "¿qué compromisos vencen esta
semana?" (aceptación F1) se responde con evidencia trazable. Decisiones y
preguntas abiertas se extraen pero su materialización en grafo llega en F1.1
(ver docs/decisions/0006).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from cortex.events.models import Event
from cortex.events.store import EventStore
from cortex.extraction.extractor import DeterministicExtractor, Extractor
from cortex.extraction.models import ExtractedEntity
from cortex.memory.chunking import chunks_for_event
from cortex.memory.chunks import InMemoryChunkIndex
from cortex.memory.embeddings import Embedder, HashingEmbedder, build_embedder
from cortex.memory.graph import InMemoryGraph
from cortex.memory.resolution import (
    DisambiguationQueue,
    EntityResolver,
    NeedsDisambiguation,
    Resolved,
    Unresolved,
)

# Relaciones de valor único que se cierran por contradicción (§7 paso 5). En F1
# las relaciones extraídas (emailed, member_of, committed) NO son single-valued,
# así que la ontología exclusiva arranca vacía y crece por configuración.
EXCLUSIVE_RELS: frozenset[str] = frozenset()

COMMITMENT_KIND = "commitment"


@dataclass
class BuildStats:
    """Conteos acumulados de una reconstrucción de la memoria de grafo."""

    events_read: int = 0
    entities_built: int = 0
    relations_built: int = 0
    commitments_built: int = 0
    chunks_built: int = 0
    disambiguations_pending: int = 0


@dataclass
class BuildResult:
    """Resultado de construir la memoria: el grafo, el índice semántico, la
    bandeja y las estadísticas."""

    graph: InMemoryGraph
    disambiguation_queue: DisambiguationQueue
    stats: BuildStats = field(default_factory=BuildStats)
    chunk_index: InMemoryChunkIndex = field(default_factory=InMemoryChunkIndex)
    embedder: Embedder = field(default_factory=HashingEmbedder)


def _commitment_key(who: str, what: str, due: date | None) -> str:
    """Clave estable para UNIQUE(kind,name) del compromiso (idempotente en rebuild)."""
    return f"{who}\x00{what[:120]}\x00{due.isoformat() if due else ''}"


def process_event(event: Event, result_extractor: Extractor, build: BuildResult) -> None:
    """Procesa UN evento: extrae, resuelve y escribe al grafo con evidencia.

    `evidence_event` y `valid_from` salen del evento (id y ts). Una entidad de
    baja confianza va a la bandeja de desambiguación y NO se escribe (§6).
    """
    graph = build.graph
    resolver = EntityResolver(graph)
    queue = build.disambiguation_queue
    result = result_extractor.extract(event)

    # Cache por evento: cada (kind,name) se resuelve una sola vez.
    cache: dict[tuple[str, str], UUID | None] = {}

    def resolve_or_create(kind: str, name: str, aliases: list[str]) -> UUID | None:
        key = (kind, name)
        if key in cache:
            return cache[key]
        extracted = ExtractedEntity(kind=kind, name=name, aliases=aliases)
        resolution = resolver.resolve(extracted)
        entity_id: UUID | None
        if isinstance(resolution, Resolved):
            entity_id = resolution.entity_id
            if aliases:  # alimentar aliases nuevos a la entidad existente
                rec = graph.get_entity(entity_id)
                if rec is not None:
                    graph.upsert_entity(
                        rec.kind, rec.name, aliases=aliases, first_seen_event=rec.first_seen_event
                    )
        elif isinstance(resolution, Unresolved):
            rec = graph.upsert_entity(kind, name, aliases=aliases, first_seen_event=event.id)
            entity_id = rec.id
        else:  # NeedsDisambiguation
            assert isinstance(resolution, NeedsDisambiguation)
            queue.enqueue(resolution)
            build.stats.disambiguations_pending = len(queue.pending())
            entity_id = None
        cache[key] = entity_id
        return entity_id

    for ent in result.entities:
        resolve_or_create(ent.kind, ent.name, list(ent.aliases))

    for rel in result.relations:
        src_id = resolve_or_create(rel.src_kind, rel.src_name, [])
        dst_id = resolve_or_create(rel.dst_kind, rel.dst_name, [])
        if src_id is not None and dst_id is not None:
            graph.add_relation(
                src_id, rel.rel, dst_id,
                evidence_event=event.id, valid_from=event.ts, confidence=rel.confidence,
            )
            build.stats.relations_built += 1

    for commitment in result.commitments:
        ckey = _commitment_key(commitment.who, commitment.what, commitment.due)
        centity = graph.upsert_entity(
            COMMITMENT_KIND,
            ckey,
            attrs={
                "what": commitment.what,
                "due": commitment.due.isoformat() if commitment.due else None,
                "direction": commitment.direction,
                "confidence": commitment.confidence,
            },
            first_seen_event=event.id,
        )
        who_id = (
            resolve_or_create("person", commitment.who, [])
            if commitment.who and commitment.who != "desconocido"
            else None
        )
        if who_id is not None:
            graph.add_relation(
                who_id, "committed", centity.id,
                evidence_event=event.id, valid_from=event.ts, confidence=commitment.confidence,
            )
            build.stats.relations_built += 1
        build.stats.commitments_built += 1

    # Índice semántico (§7 paso 6): trocear el texto del evento, embeber cada
    # chunk y etiquetarlo con las entidades resueltas en ESTE evento (para el
    # filtrado del retrieval híbrido, §8). Costo $0 con el HashingEmbedder.
    event_entity_ids = [eid for eid in cache.values() if eid is not None]
    pieces = chunks_for_event(event)
    if pieces:
        vectors = build.embedder.embed(pieces)
        for text, vector in zip(pieces, vectors):
            build.chunk_index.add(
                event_id=event.id,
                text=text,
                embedding=vector,
                embed_model=build.embedder.model,
                entity_ids=event_entity_ids,
            )
            build.stats.chunks_built += 1

    build.stats.entities_built = len(graph.entities_all())


def build_memory(
    store: EventStore,
    extractor: Extractor | None = None,
    *,
    embedder: Embedder | None = None,
) -> BuildResult:
    """Reconstruye la memoria (grafo + índice semántico) leyendo el log en orden.

    Determinista y sin efectos sobre el log. El extractor por defecto es el
    determinista y el embedder por defecto es el Hashing (costo $0 ambos).
    Devuelve el grafo, el índice de chunks, la bandeja y las estadísticas.
    """
    ext = extractor if extractor is not None else DeterministicExtractor()
    emb = embedder if embedder is not None else build_embedder()
    graph = InMemoryGraph(exclusive_rels=EXCLUSIVE_RELS)
    build = BuildResult(
        graph=graph, disambiguation_queue=DisambiguationQueue(graph), embedder=emb
    )
    for event in store.all_events():
        build.stats.events_read += 1
        process_event(event, ext, build)
    build.stats.entities_built = len(graph.entities_all())
    return build


def commitments_due_between(
    graph: InMemoryGraph, start: datetime, end: datetime
) -> list[UUID]:
    """Ids de entidades `commitment` con `due` en [start, end] (aceptación F1).

    Sólo cuenta compromisos con fecha explícita (los sin fecha no vencen "esta
    semana" por definición; principio 2: no inventamos vencimientos)."""
    out: list[UUID] = []
    for rec in graph.entities_by_kind(COMMITMENT_KIND):
        due_raw = rec.attrs.get("due")
        if not isinstance(due_raw, str):
            continue
        due = date.fromisoformat(due_raw)
        if start.date() <= due <= end.date():
            out.append(rec.id)
    return out
