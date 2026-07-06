"""Integración contra un Postgres real (F0: log append-only sobre la base).

Se salta automáticamente si no hay Postgres alcanzable (dev local sin Docker):
así la suite corre en verde en cualquier máquina, y en CI —donde el workflow
levanta un pgvector y aplica `alembic upgrade head`— verifica de verdad la
persistencia, la idempotencia por external_id y el trigger append-only (§6).

Requiere que la migración ya esté aplicada (el CI corre `alembic upgrade head`
antes de pytest). No borra datos: usa external_ids únicos por corrida y el
trigger prohíbe DELETE por diseño.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Iterator

import pytest
import sqlalchemy as sa

from cortex.events.models import EventIn
from cortex.events.store import PostgresEventStore
from cortex.settings import get_settings


def _engine_or_skip() -> sa.Engine:
    dsn = get_settings().postgres_dsn
    try:
        engine = sa.create_engine(dsn, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
            # La migración debe estar aplicada (tabla events presente).
            conn.execute(sa.text("SELECT 1 FROM events LIMIT 1"))
    except Exception as exc:  # noqa: BLE001 - cualquier fallo de infra → skip
        pytest.skip(f"Postgres no disponible / no migrado: {exc}")
    return engine


@pytest.fixture(scope="module")
def engine() -> Iterator[sa.Engine]:
    eng = _engine_or_skip()
    yield eng
    eng.dispose()


def _event(external_id: str, body: str) -> EventIn:
    return EventIn(
        ts=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        source="gmail",
        type="email.received",
        external_id=external_id,
        actor="alguien@externo.com",
        payload={"from": "alguien@externo.com", "body": body},
        pipeline_ver="0.1.0-itest",
    )


def test_append_persists_and_is_idempotent(engine: sa.Engine) -> None:
    store = PostgresEventStore(engine)
    ext_id = f"itest-{uuid.uuid4()}"

    inserted = store.append(_event(ext_id, "primero"))
    assert inserted is not None
    assert inserted.id > 0

    # Re-append del mismo external_id no duplica (ON CONFLICT DO NOTHING).
    dup = store.append(_event(ext_id, "otra vez"))
    assert dup is None


def test_events_are_append_only_update_and_delete_blocked(engine: sa.Engine) -> None:
    store = PostgresEventStore(engine)
    ext_id = f"itest-{uuid.uuid4()}"
    inserted = store.append(_event(ext_id, "inmutable"))
    assert inserted is not None

    # El trigger de la migración rechaza UPDATE y DELETE (principio 1).
    with pytest.raises(Exception):  # noqa: B017 - psycopg envuelve la RAISE del trigger
        with engine.begin() as conn:
            conn.execute(
                sa.text("UPDATE events SET actor = :a WHERE id = :id"),
                {"a": "hacker", "id": inserted.id},
            )
    with pytest.raises(Exception):  # noqa: B017
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM events WHERE id = :id"), {"id": inserted.id})
