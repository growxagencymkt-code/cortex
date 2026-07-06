"""CLI de CORTEX.

Comandos F0:
    cortex rebuild --from-events [--store postgres|memory]

`rebuild --from-events` reconstruye las vistas derivadas desde el log
(principio 1: siempre disponible y testeado). Con --store memory corre
sin base de datos (smoke test); por defecto usa el Postgres de settings.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

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
    return parser


def _make_store(kind: str) -> EventStore:
    if kind == "memory":
        return InMemoryEventStore()
    return postgres_store_from_dsn(get_settings().postgres_dsn)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "rebuild":
        try:
            store = _make_store(args.store)
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
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
