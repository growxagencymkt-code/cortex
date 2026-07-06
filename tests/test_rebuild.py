"""rebuild --from-events: siempre disponible y en verde (principio 1)."""

from __future__ import annotations

from cortex.cli import main as cli_main
from cortex.connectors.base import ingest
from cortex.events.rebuild import rebuild_from_events
from cortex.events.store import InMemoryEventStore
from tests.conftest import PIPELINE_VER_TEST, FakeMailConnector, make_mail_item


def test_rebuild_from_events_runs_green_on_empty_log(store: InMemoryEventStore) -> None:
    report = rebuild_from_events(store)
    assert report.events_read == 0
    assert report.entities_built == 0


def test_rebuild_reads_full_log_without_mutating_it(store: InMemoryEventStore) -> None:
    connector = FakeMailConnector([make_mail_item(f"msg-{i:03d}", f"cuerpo {i}") for i in range(7)])
    ingest(connector, store, pipeline_ver=PIPELINE_VER_TEST)

    report = rebuild_from_events(store)
    assert report.events_read == 7
    # F1: el rebuild construye el grafo. Los 7 mails comparten remitente/destinatario
    # (alguien@externo.com → fundador@ejemplo.com), así que las entidades deduplican
    # y las relaciones (emailed, member_of) se acumulan con su evidence_event.
    assert report.entities_built >= 4  # 2 personas + 2 orgs por dominio
    assert report.relations_built > 0
    assert report.chunks_built > 0  # F2: el índice semántico se construye en el rebuild
    # El log no se tocó (principio 1).
    assert store.count() == 7


def test_cli_rebuild_from_events_memory_exits_zero() -> None:
    assert cli_main(["rebuild", "--from-events", "--store", "memory"]) == 0
