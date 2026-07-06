"""Conector de notas/documentos — stub, llega en F1+."""

from __future__ import annotations

from typing import Iterable

from cortex.connectors.base import Connector, RawItem


class NotesConnector(Connector):
    """Notas y documentos del fundador como eventos del log."""

    source = "notes"
    event_type = "note.captured"

    def fetch_new(self) -> Iterable[RawItem]:
        raise NotImplementedError("NotesConnector: integración real en F1+.")
