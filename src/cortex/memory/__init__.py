"""Memoria en 3 vistas: grafo, índice semántico (pgvector), procesos — F1/F2.

F1 expone el grafo de entidades/relaciones con evidencia y la cascada de
resolución/desambiguación de entidades. Todo en memoria (DB-agnóstico), espejando
1:1 el contrato Postgres de la sección 6 del SYSTEM_PROMPT.
"""

from __future__ import annotations

from cortex.memory.graph import EntityRecord, InMemoryGraph, RelationRecord
from cortex.memory.resolution import (
    CONFIDENCE_THRESHOLD,
    DisambiguationQueue,
    Embedder,
    EntityResolver,
    NeedsDisambiguation,
    Resolved,
    Unresolved,
)

__all__ = [
    "InMemoryGraph",
    "EntityRecord",
    "RelationRecord",
    "EntityResolver",
    "Resolved",
    "NeedsDisambiguation",
    "Unresolved",
    "DisambiguationQueue",
    "Embedder",
    "CONFIDENCE_THRESHOLD",
]
