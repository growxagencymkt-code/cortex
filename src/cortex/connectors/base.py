"""Contrato base de conectores + ingesta idempotente por external_id."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict

from cortex.events.models import EventIn
from cortex.events.store import EventStore


class RawItem(BaseModel):
    """Ítem crudo traído por un conector, aún sin normalizar a evento.

    external_id identifica el ítem en la fuente (p.ej. message id de Gmail)
    y es la clave de idempotencia: re-correr la ingesta no duplica.
    payload conserva el crudo COMPLETO de la fuente (sección 7, paso 2).
    """

    model_config = ConfigDict(frozen=True)

    external_id: str
    ts: datetime
    actor: str | None = None
    payload: dict[str, Any]


class Connector(ABC):
    """Conector de percepción. Trae ítems nuevos de una fuente; no interpreta.

    Subclases definen `source` (p.ej. 'gmail') y `event_type`
    (p.ej. 'email.received') y implementan fetch_new().
    """

    source: str
    event_type: str

    @abstractmethod
    def fetch_new(self) -> Iterable[RawItem]:
        """Devuelve los ítems nuevos de la fuente (puede repetir ya vistos:
        la idempotencia la garantiza la ingesta por external_id)."""
        raise NotImplementedError


class IngestReport(BaseModel):
    """Resultado de una corrida de ingesta."""

    model_config = ConfigDict(frozen=True)

    source: str
    fetched: int
    inserted: int
    skipped_duplicates: int


def ingest(connector: Connector, store: EventStore, *, pipeline_ver: str) -> IngestReport:
    """Pipeline de ingesta F0 (sección 7, pasos 1–2).

    1. El conector trae ítems nuevos.
    2. Se normalizan a evento {ts, source, type, actor, payload} y se
       appendean al log. Idempotencia por external_id: el store descarta
       duplicados, por lo que re-correr la ingesta no duplica eventos.
    """
    fetched = inserted = skipped = 0
    for item in connector.fetch_new():
        fetched += 1
        event = EventIn(
            ts=item.ts,
            source=connector.source,
            type=connector.event_type,
            external_id=item.external_id,
            actor=item.actor,
            payload=item.payload,
            pipeline_ver=pipeline_ver,
        )
        if store.append(event) is None:
            skipped += 1
        else:
            inserted += 1
    return IngestReport(
        source=connector.source,
        fetched=fetched,
        inserted=inserted,
        skipped_duplicates=skipped,
    )
