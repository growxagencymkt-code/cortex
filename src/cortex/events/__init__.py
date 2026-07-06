"""Log de eventos append-only: la única fuente de verdad (principio 1).

Los eventos jamás se actualizan ni se borran; las correcciones son eventos
nuevos de type 'correction' que referencian al original.
"""

from cortex.events.models import Event, EventIn, make_correction
from cortex.events.rebuild import RebuildReport, rebuild_from_events
from cortex.events.store import EventStore, InMemoryEventStore, PostgresEventStore

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
