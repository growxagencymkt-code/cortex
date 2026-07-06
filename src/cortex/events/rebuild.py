"""rebuild --from-events: reconstrucción de las vistas derivadas desde el log.

El grafo, el índice semántico y los procesos son vistas descartables y
reconstruibles desde el log de eventos (principio 1). Este comando debe
estar SIEMPRE disponible y testeado.

F1: reconstruye la vista de GRAFO (entities/relations con evidence_event) vía
`memory.build.build_memory` (pipeline §7 pasos 3-5). Chunks (F2) y process_cases
(F1.1+) todavía quedan en 0: se enchufan en su fase. El log nunca se muta.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from cortex.events.store import EventStore
from cortex.extraction.extractor import Extractor
from cortex.memory.build import build_memory


class RebuildReport(BaseModel):
    """Resultado de una reconstrucción de vistas desde el log."""

    model_config = ConfigDict(frozen=True)

    events_read: int
    entities_built: int
    relations_built: int
    chunks_built: int
    process_cases_built: int
    disambiguations_pending: int = 0


def rebuild_from_events(store: EventStore, extractor: Extractor | None = None) -> RebuildReport:
    """Reconstruye las vistas derivadas leyendo el log completo en orden.

    Nunca muta el log. F1: construye el grafo con evidencia (cada relación con su
    `evidence_event`). Chunks y process_cases se agregan en F2/F1.1.
    """
    result = build_memory(store, extractor)
    stats = result.stats
    return RebuildReport(
        events_read=stats.events_read,
        entities_built=stats.entities_built,
        relations_built=stats.relations_built,
        chunks_built=0,
        process_cases_built=0,
        disambiguations_pending=stats.disambiguations_pending,
    )
