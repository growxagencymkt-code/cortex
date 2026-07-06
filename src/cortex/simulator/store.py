"""Store con corte temporal para el snapshot del simulador (SYSTEM_PROMPT §9.2).

El snapshot temporal debe construirse con SÓLO los eventos observables hasta el
instante `t` (events.ts <= t). Un hecho posterior a `t` que aparezca en el
snapshot de `t` es **fuga temporal** = bug crítico (§9.2).

`TimeFilteredEventStore` envuelve cualquier `EventStore` y expone la misma
interfaz (Protocol de `cortex.events.store`), pero `all_events()` sólo emite los
eventos con `ts <= until`. Así `build_memory()` reconstruye la memoria "como se
veía en `t`" sin tocar `events/store.py` (§9.2: no se modifica el store real).

El simulador JAMÁS escribe: `append()` está prohibido en este wrapper. El log es
la única fuente de verdad y el replay es de sólo lectura (principio 1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterator

from cortex.events.models import Event, EventIn
from cortex.events.store import EventStore


class SimulatorWriteAttempt(RuntimeError):
    """Se intentó escribir al log desde el simulador (prohibido: replay read-only)."""


class TimeFilteredEventStore:
    """EventStore de sólo lectura que corta el log en `until` (ts <= until).

    Envuelve un `EventStore` real. Preserva el orden del log subyacente (que ya
    viene ordenado por inserción/`id`). No copia eventos: filtra al vuelo.
    """

    def __init__(self, inner: EventStore, *, until: datetime) -> None:
        self._inner = inner
        self._until = until

    @property
    def until(self) -> datetime:
        return self._until

    def append(self, event: EventIn) -> Event | None:  # noqa: ARG002
        """Prohibido: el simulador nunca muta el log (replay de sólo lectura)."""
        raise SimulatorWriteAttempt(
            "El simulador no escribe al log: el replay es de sólo lectura "
            "(SYSTEM_PROMPT §9.1). Usá el store real fuera de la simulación."
        )

    def all_events(self) -> Iterator[Event]:
        """Itera SÓLO los eventos con ts <= until, en el orden del log."""
        for event in self._inner.all_events():
            if event.ts <= self._until:
                yield event

    def count(self) -> int:
        return sum(1 for _ in self.all_events())
