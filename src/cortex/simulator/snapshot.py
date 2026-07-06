"""Snapshot temporal de la memoria (SYSTEM_PROMPT §9.2).

Construye la memoria de grafo "como se veía en el instante `t`": sólo eventos con
`ts <= t` y relaciones vigentes a `t`. Reusa `cortex.memory.build.build_memory`
sobre un `TimeFilteredEventStore` (no reimplementa la construcción del grafo).

Fuga temporal (un hecho con `ts > t` visible en el snapshot de `t`) = bug crítico.
Se cubre con test dedicado (tests/test_simulator_snapshot.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from cortex.events.store import EventStore
from cortex.extraction.extractor import Extractor
from cortex.memory.build import BuildResult, build_memory, commitments_due_between
from cortex.memory.graph import EntityRecord, InMemoryGraph, RelationRecord
from cortex.simulator.store import TimeFilteredEventStore


@dataclass(frozen=True)
class MemorySnapshot:
    """La memoria congelada al instante `t`. Sólo lectura.

    `graph` contiene únicamente hechos derivados de eventos con `ts <= t`. Las
    relaciones vigentes a `t` se consultan con `relations_valid_at` (que filtra
    por `valid_from <= t < valid_to`), evitando fuga temporal por partida doble:
    ni eventos futuros, ni relaciones cerradas después de `t`.
    """

    t: datetime
    graph: InMemoryGraph
    build: BuildResult

    def relations_valid_at(self, src_id: UUID) -> list[RelationRecord]:
        """Relaciones de `src_id` vigentes exactamente en `t` (sin futuro)."""
        return self.graph.relations_valid_at(src_id, self.t)

    def entities_by_kind(self, kind: str) -> list[EntityRecord]:
        return self.graph.entities_by_kind(kind)

    def find_entity(self, kind: str, text: str) -> EntityRecord | None:
        return self.graph.find_by_name_or_alias(kind, text)

    def commitments_due(self, start: datetime, end: datetime) -> list[UUID]:
        return commitments_due_between(self.graph, start, end)

    def entity_names(self) -> list[str]:
        """Nombres y alias de todas las entidades (para fundamentar destinatarios)."""
        out: list[str] = []
        for rec in self.graph.entities_all():
            out.append(rec.name)
            out.extend(rec.aliases)
        return out


def build_snapshot(
    store: EventStore, t: datetime, *, extractor: Extractor | None = None
) -> MemorySnapshot:
    """Reconstruye la memoria con SÓLO los eventos hasta `t` (ts <= t).

    Determinista (mismo log + mismo `t` → mismo snapshot). No toca el store real
    ni el log: usa un `TimeFilteredEventStore` de sólo lectura.
    """
    filtered = TimeFilteredEventStore(store, until=t)
    result = build_memory(filtered, extractor)
    return MemorySnapshot(t=t, graph=result.graph, build=result)
