"""Escritura y lectura del log de eventos append-only.

La interfaz EventStore expone SOLO append y lectura: no existen update ni
delete a propósito (principio 1). El Postgres además lo refuerza con un
trigger que rechaza UPDATE/DELETE sobre events (migración inicial).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterator, Protocol

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert

from cortex.events.models import Event, EventIn

_metadata = sa.MetaData()

# Espejo mínimo de la tabla `events` (el DDL canónico vive en migrations/).
events_table = sa.Table(
    "events",
    _metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("ingested_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("source", sa.Text, nullable=False),
    sa.Column("type", sa.Text, nullable=False),
    sa.Column("external_id", sa.Text, unique=True),
    sa.Column("actor", sa.Text),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("pipeline_ver", sa.Text, nullable=False),
)


class EventStore(Protocol):
    """Contrato del log de eventos. Append-only: sin update, sin delete."""

    def append(self, event: EventIn) -> Event | None:
        """Agrega el evento al log. Devuelve el Event persistido,
        o None si ya existía un evento con el mismo external_id (idempotencia)."""
        ...

    def all_events(self) -> Iterator[Event]:
        """Itera el log completo en orden de inserción (para rebuild y replay)."""
        ...

    def count(self) -> int:
        """Cantidad total de eventos en el log."""
        ...


class InMemoryEventStore:
    """Implementación en memoria del EventStore.

    Mismo contrato que Postgres (idempotencia por external_id, append-only).
    Se usa en tests y para smoke-runs sin base de datos.
    """

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._external_ids: set[str] = set()

    def append(self, event: EventIn) -> Event | None:
        if event.external_id is not None:
            if event.external_id in self._external_ids:
                return None
            self._external_ids.add(event.external_id)
        persisted = Event(
            id=len(self._events) + 1,
            ingested_at=datetime.now(tz=UTC),
            **event.model_dump(),
        )
        self._events.append(persisted)
        return persisted

    def all_events(self) -> Iterator[Event]:
        return iter(tuple(self._events))

    def count(self) -> int:
        return len(self._events)


class PostgresEventStore:
    """Implementación Postgres del EventStore (SQLAlchemy Core, psycopg).

    Idempotencia por external_id vía ON CONFLICT DO NOTHING: re-correr una
    ingesta no duplica eventos (criterio de aceptación F0).
    """

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def append(self, event: EventIn) -> Event | None:
        insert_stmt = pg_insert(events_table).values(
            ts=event.ts,
            source=event.source,
            type=event.type,
            external_id=event.external_id,
            actor=event.actor,
            payload=event.payload,
            pipeline_ver=event.pipeline_ver,
        )
        # El ON CONFLICT se aplica sobre el Insert del dialecto pg ANTES de
        # .returning() (que devuelve un ReturningInsert sin ese método).
        if event.external_id is not None:
            insert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=["external_id"])
        stmt = insert_stmt.returning(events_table.c.id, events_table.c.ingested_at)
        with self._engine.begin() as conn:
            row = conn.execute(stmt).first()
        if row is None:  # conflicto: ya ingerido
            return None
        return Event(id=row.id, ingested_at=row.ingested_at, **event.model_dump())

    def all_events(self) -> Iterator[Event]:
        stmt = sa.select(events_table).order_by(events_table.c.id)
        with self._engine.connect() as conn:
            for row in conn.execute(stmt).mappings():
                yield Event.model_validate(dict(row))

    def count(self) -> int:
        stmt = sa.select(sa.func.count()).select_from(events_table)
        with self._engine.connect() as conn:
            result = conn.execute(stmt).scalar_one()
        return int(result)


def postgres_store_from_dsn(dsn: str) -> PostgresEventStore:
    """Crea un PostgresEventStore desde un DSN SQLAlchemy (settings.postgres_dsn)."""
    return PostgresEventStore(sa.create_engine(dsn, pool_pre_ping=True))
