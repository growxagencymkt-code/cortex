"""Conector de reuniones (transcripciones Whisper ingeridas como archivo) — stub F1+."""

from __future__ import annotations

from typing import Iterable

from cortex.connectors.base import Connector, RawItem


class MeetingsConnector(Connector):
    """Transcripciones de reuniones como eventos del log."""

    source = "meetings"
    event_type = "meeting.transcript"

    def fetch_new(self) -> Iterable[RawItem]:
        raise NotImplementedError("MeetingsConnector: integración real en F1+.")
