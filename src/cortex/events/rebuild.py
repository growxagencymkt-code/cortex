"""rebuild --from-events: reconstrucción de las vistas derivadas desde el log.

El grafo, el índice semántico y los procesos son vistas descartables y
reconstruibles desde el log de eventos (principio 1). Este comando debe
estar SIEMPRE disponible y testeado.

F0: las vistas todavía no existen, así que el rebuild recorre el log
completo y deja las vistas vacías — pero el mecanismo, el contrato y sus
tests ya quedan cimentados. En F1/F2 acá se enchufan grafo, chunks y casos.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from cortex.events.store import EventStore


class RebuildReport(BaseModel):
    """Resultado de una reconstrucción de vistas desde el log."""

    model_config = ConfigDict(frozen=True)

    events_read: int
    entities_built: int
    relations_built: int
    chunks_built: int
    process_cases_built: int


def rebuild_from_events(store: EventStore) -> RebuildReport:
    """Reconstruye todas las vistas derivadas leyendo el log completo en orden.

    Nunca muta el log. En F0 las vistas quedan vacías por diseño.
    """
    events_read = 0
    for _event in store.all_events():
        events_read += 1
        # F1: reconstruir grafo (entities/relations con evidence_event).
        # F2: reconstruir chunks + embeddings.
        # F1: reconstruir process_cases.
    return RebuildReport(
        events_read=events_read,
        entities_built=0,
        relations_built=0,
        chunks_built=0,
        process_cases_built=0,
    )
