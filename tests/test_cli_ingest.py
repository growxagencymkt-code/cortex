"""Tests del comando `cortex ingest` (seed idempotente desde un JSONL).

Corre en --store memory (costo $0, sin base de datos): ejercita el camino
conector→ingesta→log y la idempotencia por external_id. El corpus es el mismo
fixture que usa el conector de fixtures.
"""

from __future__ import annotations

from pathlib import Path

from cortex.cli import main as cli_main
from cortex.connectors.base import ingest
from cortex.connectors.fixture import FixtureMailConnector
from cortex.events.store import InMemoryEventStore

_FIXTURE = Path(__file__).parent / "fixtures" / "sample_emails.jsonl"


def test_cli_ingest_memory_exits_zero() -> None:
    assert cli_main(["ingest", "--fixture", str(_FIXTURE), "--store", "memory"]) == 0


def test_cli_ingest_missing_fixture_returns_error_code() -> None:
    assert cli_main(["ingest", "--fixture", "no/existe.jsonl", "--store", "memory"]) == 2


def test_ingest_is_idempotent_by_external_id() -> None:
    store = InMemoryEventStore()
    connector = FixtureMailConnector(_FIXTURE)

    first = ingest(connector, store, pipeline_ver="0.1.0-test")
    assert first.inserted > 0
    assert first.skipped_duplicates == 0
    inserted_count = store.count()

    # Re-correr la misma ingesta NO duplica (criterio de aceptación F0).
    second = ingest(connector, store, pipeline_ver="0.1.0-test")
    assert second.inserted == 0
    assert second.skipped_duplicates == first.inserted
    assert store.count() == inserted_count
