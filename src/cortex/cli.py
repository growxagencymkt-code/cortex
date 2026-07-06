"""CLI de CORTEX.

Comandos F0:
    cortex rebuild --from-events [--store postgres|memory]
    cortex ingest --fixture <PATH.jsonl> [--store postgres|memory]

`rebuild --from-events` reconstruye las vistas derivadas desde el log
(principio 1: siempre disponible y testeado). `ingest --fixture` carga un corpus
JSONL de mails al log de forma idempotente (seed local / import de export propio).
Con --store memory ambos corren sin base de datos (smoke test); por defecto usan
el Postgres de settings.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from cortex.connectors.base import ingest
from cortex.connectors.fixture import FixtureMailConnector
from cortex.events.rebuild import rebuild_from_events
from cortex.events.store import EventStore, InMemoryEventStore, postgres_store_from_dsn
from cortex.settings import get_settings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cortex", description="CORTEX — cerebro operativo agentivo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    rebuild = subparsers.add_parser("rebuild", help="Reconstruye las vistas derivadas")
    rebuild.add_argument(
        "--from-events",
        action="store_true",
        required=True,
        help="Reconstruir desde el log de eventos (única fuente de verdad)",
    )
    rebuild.add_argument(
        "--store",
        choices=("postgres", "memory"),
        default="postgres",
        help="Backend del log: postgres (settings.postgres_dsn) o memory (smoke)",
    )

    ingest_cmd = subparsers.add_parser(
        "ingest", help="Ingesta idempotente de un corpus JSONL de mails al log"
    )
    ingest_cmd.add_argument(
        "--fixture",
        required=True,
        help="Ruta al JSONL de mails ({external_id, ts, from, to, subject, body})",
    )
    ingest_cmd.add_argument(
        "--store",
        choices=("postgres", "memory"),
        default="postgres",
        help="Backend del log: postgres (settings.postgres_dsn) o memory (smoke)",
    )
    return parser


def _make_store(kind: str) -> EventStore:
    if kind == "memory":
        return InMemoryEventStore()
    return postgres_store_from_dsn(get_settings().postgres_dsn)


def _run_rebuild(store_kind: str) -> int:
    try:
        store = _make_store(store_kind)
        report = rebuild_from_events(store)
    except Exception as exc:  # p.ej. Postgres no disponible
        print(f"rebuild fallo: {exc}", file=sys.stderr)
        return 2
    print(
        "rebuild OK — "
        f"eventos leidos: {report.events_read}, "
        f"entidades: {report.entities_built}, "
        f"relaciones: {report.relations_built}, "
        f"chunks: {report.chunks_built}, "
        f"casos: {report.process_cases_built}"
    )
    return 0


def _run_ingest(store_kind: str, fixture_path: str) -> int:
    try:
        store = _make_store(store_kind)
        connector = FixtureMailConnector(fixture_path)
        report = ingest(connector, store, pipeline_ver=get_settings().pipeline_ver)
    except Exception as exc:  # p.ej. archivo inexistente / Postgres no disponible
        print(f"ingest fallo: {exc}", file=sys.stderr)
        return 2
    print(
        "ingest OK — "
        f"fuente: {report.source}, "
        f"traidos: {report.fetched}, "
        f"insertados: {report.inserted}, "
        f"duplicados omitidos: {report.skipped_duplicates}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "rebuild":
        return _run_rebuild(args.store)
    if args.command == "ingest":
        return _run_ingest(args.store, args.fixture)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
