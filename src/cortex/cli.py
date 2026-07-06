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
from datetime import UTC, datetime, timedelta
from typing import Sequence

from cortex.connectors.base import ingest
from cortex.connectors.fixture import FixtureMailConnector
from cortex.events.rebuild import rebuild_from_events
from cortex.events.store import EventStore, InMemoryEventStore, postgres_store_from_dsn
from cortex.memory.build import build_memory, commitments_due_between
from cortex.memory.retrieval import answer_query
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

    ask = subparsers.add_parser("ask", help="Recuperación híbrida fundamentada (§8)")
    ask.add_argument("query", help="La consulta en lenguaje natural")
    ask.add_argument("--store", choices=("postgres", "memory"), default="postgres")
    ask.add_argument(
        "--fixture", default=None, help="JSONL a ingerir antes de responder (útil con --store memory)"
    )

    digest = subparsers.add_parser("digest", help="Resumen: compromisos que vencen (§13 F2)")
    digest.add_argument("--store", choices=("postgres", "memory"), default="postgres")
    digest.add_argument("--fixture", default=None, help="JSONL a ingerir antes del resumen")
    digest.add_argument("--days", type=int, default=7, help="Ventana en días (default 7)")
    return parser


def _make_store(kind: str) -> EventStore:
    if kind == "memory":
        return InMemoryEventStore()
    return postgres_store_from_dsn(get_settings().postgres_dsn)


def _store_maybe_seeded(kind: str, fixture: str | None) -> EventStore:
    """Store del tipo pedido, opcionalmente sembrado con un corpus JSONL."""
    store = _make_store(kind)
    if fixture:
        ingest(FixtureMailConnector(fixture), store, pipeline_ver=get_settings().pipeline_ver)
    return store


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


def _run_ask(store_kind: str, query: str, fixture: str | None) -> int:
    try:
        store = _store_maybe_seeded(store_kind, fixture)
        result = answer_query(store, query)
    except Exception as exc:  # p.ej. Postgres no disponible / fixture inexistente
        print(f"ask fallo: {exc}", file=sys.stderr)
        return 2
    if not result.answerable:
        print(f"No sé. {result.note}")
        return 0
    print(f"Consulta: {result.query}")
    if result.facts:
        print("Hechos (con evidencia):")
        for f in result.facts:
            print(f"  - {f.src} --{f.rel}-> {f.dst}  [evento {f.evidence_event}]")
    if result.chunks:
        print("Fragmentos:")
        for c in result.chunks:
            snippet = " ".join(c.text.split())[:100]
            print(f"  - [{c.source} evento {c.event_id} score {c.score:.3f}] {snippet}")
    return 0


def _run_digest(store_kind: str, fixture: str | None, days: int) -> int:
    try:
        store = _store_maybe_seeded(store_kind, fixture)
        memory = build_memory(store)
    except Exception as exc:
        print(f"digest fallo: {exc}", file=sys.stderr)
        return 2
    now = datetime.now(tz=UTC)
    end = now + timedelta(days=days)
    due = commitments_due_between(memory.graph, now, end)
    print(f"Resumen — compromisos que vencen en {days} dias:")
    if not due:
        print("  (ninguno con fecha en la ventana)")
    for eid in due:
        rec = memory.graph.get_entity(eid)
        if rec is None:
            continue
        print(f"  - {rec.attrs.get('what')} (vence {rec.attrs.get('due')}) [evento {rec.first_seen_event}]")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "rebuild":
        return _run_rebuild(args.store)
    if args.command == "ingest":
        return _run_ingest(args.store, args.fixture)
    if args.command == "ask":
        return _run_ask(args.store, args.query, args.fixture)
    if args.command == "digest":
        return _run_digest(args.store, args.fixture, args.days)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
