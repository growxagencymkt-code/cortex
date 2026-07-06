"""Índice semántico de chunks (SYSTEM_PROMPT §6 tabla `chunks`) — F2.

Vista derivada del log (principio 1): descartable y reconstruible. Cada chunk
apunta a su `event_id` (evidencia, principio 2) y lleva los `entity_ids` que se
resolvieron en ese evento, para el filtrado del retrieval híbrido (§8).

Implementación **en memoria**, DB-agnóstica, que espeja el contrato SQL:

    chunks(id BIGSERIAL PK, event_id BIGINT REFERENCES events(id),
           entity_ids UUID[] DEFAULT '{}', text TEXT NOT NULL,
           embedding VECTOR(dim), embed_model TEXT NOT NULL)
    INDEX USING GIN(entity_ids)

La búsqueda por `entity_ids` espeja el índice GIN (chunks que comparten al menos
una entidad). La búsqueda vectorial es coseno (pgvector hará lo propio a escala).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cortex.memory.embeddings import cosine


class ChunkRecord(BaseModel):
    """Una fila de `chunks`: fragmento indexado con su evidencia y entidades."""

    model_config = ConfigDict(frozen=True)

    id: int
    event_id: int
    entity_ids: list[UUID] = Field(default_factory=list)
    text: str
    embedding: list[float]
    embed_model: str


class ScoredChunk(BaseModel):
    """Un chunk recuperado con su score de similitud (coseno)."""

    model_config = ConfigDict(frozen=True)

    chunk: ChunkRecord
    score: float


class InMemoryChunkIndex:
    """Índice de chunks en memoria con búsqueda coseno y filtro por entidades."""

    def __init__(self) -> None:
        self._chunks: list[ChunkRecord] = []
        self._counter = 0

    def add(
        self,
        *,
        event_id: int,
        text: str,
        embedding: list[float],
        embed_model: str,
        entity_ids: list[UUID] | None = None,
    ) -> ChunkRecord:
        self._counter += 1
        record = ChunkRecord(
            id=self._counter,
            event_id=event_id,
            entity_ids=list(entity_ids or []),
            text=text,
            embedding=embedding,
            embed_model=embed_model,
        )
        self._chunks.append(record)
        return record

    def search(
        self,
        query: list[float],
        *,
        top_k: int = 5,
        entity_ids: list[UUID] | None = None,
        min_score: float = 0.0,
    ) -> list[ScoredChunk]:
        """Top-`top_k` chunks por coseno.

        Si `entity_ids` se pasa, filtra a los chunks que comparten al menos una
        entidad (espeja el índice GIN). Si es None, busca en todo el índice.
        Descarta scores <= `min_score`. Orden estable (score desc, luego id asc).
        """
        wanted = set(entity_ids) if entity_ids else None
        scored: list[ScoredChunk] = []
        for chunk in self._chunks:
            if wanted is not None and not (wanted & set(chunk.entity_ids)):
                continue
            score = cosine(query, chunk.embedding)
            if score >= min_score:  # incluye ortogonales (0); excluye opuestos (<0)
                scored.append(ScoredChunk(chunk=chunk, score=score))
        scored.sort(key=lambda s: (-s.score, s.chunk.id))
        return scored[:top_k]

    def all_chunks(self) -> list[ChunkRecord]:
        return list(self._chunks)

    def count(self) -> int:
        return len(self._chunks)
