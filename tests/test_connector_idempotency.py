"""Criterio de aceptación F0: re-correr la ingesta NO duplica eventos."""

from __future__ import annotations

from cortex.connectors.base import ingest
from cortex.events.store import InMemoryEventStore
from tests.conftest import PIPELINE_VER_TEST, FakeMailConnector, make_mail_item


def test_reingest_does_not_duplicate(store: InMemoryEventStore) -> None:
    connector = FakeMailConnector(
        [
            make_mail_item("msg-001", "hola"),
            make_mail_item("msg-002", "propuesta adjunta"),
            make_mail_item("msg-003", "minuta de reunion"),
        ]
    )

    first = ingest(connector, store, pipeline_ver=PIPELINE_VER_TEST)
    assert first.fetched == 3
    assert first.inserted == 3
    assert first.skipped_duplicates == 0
    assert store.count() == 3

    second = ingest(connector, store, pipeline_ver=PIPELINE_VER_TEST)
    assert second.fetched == 3
    assert second.inserted == 0
    assert second.skipped_duplicates == 3
    assert store.count() == 3  # ni un evento más


def test_duplicates_within_single_run_are_skipped(store: InMemoryEventStore) -> None:
    connector = FakeMailConnector(
        [make_mail_item("msg-001", "hola"), make_mail_item("msg-001", "hola")]
    )
    report = ingest(connector, store, pipeline_ver=PIPELINE_VER_TEST)
    assert report.inserted == 1
    assert report.skipped_duplicates == 1
    assert store.count() == 1


def test_event_preserves_raw_payload_and_stamps_pipeline_ver(store: InMemoryEventStore) -> None:
    connector = FakeMailConnector([make_mail_item("msg-042", "contenido crudo intacto")])
    ingest(connector, store, pipeline_ver=PIPELINE_VER_TEST)
    event = next(store.all_events())
    assert event.source == "gmail"
    assert event.type == "email.received"
    assert event.external_id == "msg-042"
    assert event.payload["body"] == "contenido crudo intacto"
    assert event.pipeline_ver == PIPELINE_VER_TEST
