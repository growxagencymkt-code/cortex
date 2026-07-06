"""Contratos de datos del log de eventos (Pydantic v2, inmutables)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventIn(BaseModel):
    """Evento normalizado, listo para append al log.

    Inmutable por diseño (frozen=True): un evento nunca se muta.
    El payload conserva el crudo completo de la fuente (sección 7, paso 2).
    """

    model_config = ConfigDict(frozen=True)

    ts: datetime
    source: str
    type: str
    external_id: str | None = None
    actor: str | None = None
    payload: dict[str, Any]
    pipeline_ver: str


class Event(EventIn):
    """Evento ya persistido en el log (con id e ingested_at asignados por la base)."""

    model_config = ConfigDict(frozen=True)

    id: int
    ingested_at: datetime


class CorrectionPayload(BaseModel):
    """Payload estándar de un evento de corrección."""

    model_config = ConfigDict(frozen=True)

    corrects_event_id: int = Field(description="id del evento original que se corrige")
    reason: str
    data: dict[str, Any] = Field(default_factory=dict)


def make_correction(
    original: Event,
    *,
    reason: str,
    data: dict[str, Any],
    actor: str,
    ts: datetime,
    pipeline_ver: str,
) -> EventIn:
    """Construye el evento de corrección para un evento ya persistido.

    Las correcciones JAMÁS mutan el original: son eventos nuevos de
    type 'correction' que lo referencian (principio 1).
    """
    payload = CorrectionPayload(corrects_event_id=original.id, reason=reason, data=data)
    return EventIn(
        ts=ts,
        source=original.source,
        type="correction",
        external_id=None,
        actor=actor,
        payload=payload.model_dump(),
        pipeline_ver=pipeline_ver,
    )
