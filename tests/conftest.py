"""Fixtures compartidas de la suite de CORTEX."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

import pytest

from cortex.connectors.base import Connector, RawItem
from cortex.events.store import InMemoryEventStore

PIPELINE_VER_TEST = "0.1.0-test"


class FakeMailConnector(Connector):
    """Conector falso con el mismo contrato que GmailConnector.

    Devuelve SIEMPRE los mismos ítems (como una fuente real re-consultada):
    la idempotencia debe garantizarla la ingesta por external_id.
    """

    source = "gmail"
    event_type = "email.received"

    def __init__(self, items: list[RawItem]) -> None:
        self._items = items

    def fetch_new(self) -> Iterable[RawItem]:
        return list(self._items)


def make_mail_item(external_id: str, body: str, sender: str = "alguien@externo.com") -> RawItem:
    payload: dict[str, Any] = {
        "from": sender,
        "to": "fundador@ejemplo.com",
        "subject": f"Mail {external_id}",
        "body": body,
    }
    return RawItem(
        external_id=external_id,
        ts=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        actor=sender,
        payload=payload,
    )


@pytest.fixture
def store() -> InMemoryEventStore:
    return InMemoryEventStore()
