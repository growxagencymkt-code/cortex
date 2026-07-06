"""Log de eventos append-only: la única fuente de verdad (principio 1).

Los eventos jamás se actualizan ni se borran; las correcciones son eventos
nuevos de type 'correction' que referencian al original.

`rebuild` depende de las capas superiores (memory + extraction), así que se
expone de forma perezosa (PEP 562): importar `cortex.events` NO arrastra
memory/extraction, lo que rompe el ciclo de importación cuando `extraction`
se importa antes que `events`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cortex.events.models import Event, EventIn, make_correction
from cortex.events.store import EventStore, InMemoryEventStore, PostgresEventStore

if TYPE_CHECKING:  # solo para type-checkers; no se ejecuta en runtime
    from cortex.events.rebuild import RebuildReport, rebuild_from_events

__all__ = [
    "Event",
    "EventIn",
    "EventStore",
    "InMemoryEventStore",
    "PostgresEventStore",
    "RebuildReport",
    "make_correction",
    "rebuild_from_events",
]

_LAZY = {"RebuildReport", "rebuild_from_events"}


def __getattr__(name: str) -> Any:
    """Carga perezosa de `rebuild` (evita el ciclo events↔memory↔extraction)."""
    if name in _LAZY:
        from cortex.events import rebuild

        return getattr(rebuild, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
