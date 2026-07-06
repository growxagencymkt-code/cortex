"""Conector de agenda (Google Calendar / CalDAV) — stub, llega en F1+."""

from __future__ import annotations

from typing import Iterable

from cortex.connectors.base import Connector, RawItem


class CalendarConnector(Connector):
    """Eventos de agenda como eventos del log. Idempotencia por id del evento."""

    source = "calendar"
    event_type = "calendar.event"

    def fetch_new(self) -> Iterable[RawItem]:
        raise NotImplementedError("CalendarConnector: integración real en F1+.")
