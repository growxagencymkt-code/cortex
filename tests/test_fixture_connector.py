"""F0: ingesta idempotente sobre un corpus realista + extraccion deterministica."""

from __future__ import annotations

from pathlib import Path

from cortex.connectors.base import ingest
from cortex.connectors.fixture import FixtureMailConnector
from cortex.events.rebuild import rebuild_from_events
from cortex.events.store import InMemoryEventStore
from cortex.extraction import DeterministicExtractor

_CORPUS = Path(__file__).parent / "fixtures" / "sample_emails.jsonl"
_EXPECTED = 12  # mails en el corpus (las lineas '#' se ignoran)


def test_corpus_ingest_is_idempotent() -> None:
    store = InMemoryEventStore()
    connector = FixtureMailConnector(_CORPUS)

    first = ingest(connector, store, pipeline_ver="0.1.0-test")
    assert first.fetched == _EXPECTED
    assert first.inserted == _EXPECTED
    assert store.count() == _EXPECTED

    # Re-correr la MISMA ingesta no agrega ni un evento (idempotencia por external_id).
    second = ingest(connector, store, pipeline_ver="0.1.0-test")
    assert second.inserted == 0
    assert second.skipped_duplicates == _EXPECTED
    assert store.count() == _EXPECTED


def test_rebuild_reads_full_corpus_without_mutating() -> None:
    store = InMemoryEventStore()
    ingest(FixtureMailConnector(_CORPUS), store, pipeline_ver="0.1.0-test")
    report = rebuild_from_events(store)
    assert report.events_read == _EXPECTED
    assert store.count() == _EXPECTED  # el log no se toca


def test_extractor_over_corpus_finds_commitments_and_dates() -> None:
    store = InMemoryEventStore()
    ingest(FixtureMailConnector(_CORPUS), store, pipeline_ver="0.1.0-test")
    ext = DeterministicExtractor()

    commitments_with_dates = 0
    orgs: set[str] = set()
    for event in store.all_events():
        result = ext.extract(event)
        commitments_with_dates += sum(1 for c in result.commitments if c.due is not None)
        orgs |= {e.name for e in result.entities if e.kind == "org"}

    # El corpus tiene varios compromisos con fecha explicita (14/07, 18/04, ...).
    assert commitments_with_dates >= 6
    # Organizaciones por dominio no generico.
    assert {"acme.com", "northwind.io", "globex.com"} <= orgs
