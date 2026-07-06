"""Servicio de memoria para la API — construye la memoria una vez y la cachea.

La memoria (grafo + índice semántico) es una vista derivada del log (principio 1):
reconstruirla por request sería O(eventos) cada vez. Este servicio la construye
una vez y la reutiliza, invalidando el caché cuando entra un evento nuevo
(ingesta). Es la capa que consumen /api/retrieve, /api/inbox y /api/panels.

Sigue siendo determinista y $0: usa el extractor determinista y el HashingEmbedder
por defecto (o el proveedor real si está configurado, vía build_embedder).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from cortex.events.models import Event
from cortex.events.store import postgres_store_from_dsn
from cortex.memory.build import BuildResult, build_memory
from cortex.memory.embeddings import Embedder, build_embedder
from cortex.memory.retrieval import RetrievalResult, retrieve
from cortex.settings import Settings


@dataclass
class MemorySnapshot:
    """Foto de la memoria construida desde el log, lista para consultar."""

    memory: BuildResult
    events_by_id: dict[int, Event]
    embedder: Embedder


class MemoryService:
    """Construye y cachea la memoria; thread-safe. Invalidable tras una ingesta."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._snapshot: MemorySnapshot | None = None
        self._lock = threading.Lock()

    def snapshot(self, *, refresh: bool = False) -> MemorySnapshot:
        with self._lock:
            if self._snapshot is None or refresh:
                store = postgres_store_from_dsn(self._settings.postgres_dsn)
                embedder = build_embedder(self._settings)
                memory = build_memory(store, embedder=embedder)
                events_by_id = {ev.id: ev for ev in store.all_events()}
                self._snapshot = MemorySnapshot(
                    memory=memory, events_by_id=events_by_id, embedder=embedder
                )
            return self._snapshot

    def invalidate(self) -> None:
        """Marca el caché como obsoleto (se reconstruye en el próximo acceso)."""
        with self._lock:
            self._snapshot = None

    def retrieve(self, query: str, *, top_k: int = 5, hops: int = 2) -> RetrievalResult:
        snap = self.snapshot()
        return retrieve(
            query,
            graph=snap.memory.graph,
            chunk_index=snap.memory.chunk_index,
            embedder=snap.embedder,
            events_by_id=snap.events_by_id,
            top_k=top_k,
            hops=hops,
        )
