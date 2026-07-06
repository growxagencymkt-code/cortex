"""Principio 1: eventos inmutables; correcciones = eventos nuevos."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cortex.events.models import make_correction
from cortex.events.store import EventStore, InMemoryEventStore
from cortex.connectors.base import ingest
from tests.conftest import PIPELINE_VER_TEST, FakeMailConnector, make_mail_item


def test_events_are_frozen(store: InMemoryEventStore) -> None:
    ingest(
        FakeMailConnector([make_mail_item("msg-001", "hola")]),
        store,
        pipeline_ver=PIPELINE_VER_TEST,
    )
    event = next(store.all_events())
    with pytest.raises(ValidationError):
        event.actor = "otro"  # type: ignore[misc]


def test_store_interface_has_no_update_or_delete() -> None:
    public_api = {name for name in dir(EventStore) if not name.startswith("_")}
    assert public_api == {"append", "all_events", "count"}
    for forbidden in ("update", "delete", "remove", "mutate"):
        assert not any(forbidden in name for name in public_api)


def test_correction_is_a_new_event_referencing_the_original(store: InMemoryEventStore) -> None:
    ingest(
        FakeMailConnector([make_mail_item("msg-001", "fecha equivocada: 12/07")]),
        store,
        pipeline_ver=PIPELINE_VER_TEST,
    )
    original = next(store.all_events())

    correction = make_correction(
        original,
        reason="la fecha correcta es 14/07",
        data={"fecha": "2026-07-14"},
        actor="human_ui:fundador",
        ts=datetime(2026, 7, 2, 9, 0, tzinfo=UTC),
        pipeline_ver=PIPELINE_VER_TEST,
    )
    persisted = store.append(correction)

    assert persisted is not None
    assert persisted.type == "correction"
    assert persisted.payload["corrects_event_id"] == original.id
    # El original sigue intacto en el log; ahora hay dos eventos.
    assert store.count() == 2
    assert next(store.all_events()).payload["body"] == "fecha equivocada: 12/07"
