"""Snapshot temporal y store con corte temporal (SYSTEM_PROMPT §9.2).

Fuga temporal (un hecho con ts > t visible en el snapshot de t) = bug crítico.
El test `test_no_temporal_leakage` lo atrapa: sin él, el simulador mediría al
agente con información del futuro (trampa que infla el acuerdo).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from cortex.events.models import EventIn
from cortex.events.store import InMemoryEventStore
from cortex.simulator.snapshot import build_snapshot
from cortex.simulator.store import SimulatorWriteAttempt, TimeFilteredEventStore

PV = "0.1.0-sim-test"


def _mail(external_id: str, sender: str, ts: datetime, body: str = "Hola.") -> EventIn:
    payload: dict[str, Any] = {
        "from": sender,
        "to": "fundador@growx.com",
        "subject": f"Asunto {external_id}",
        "body": body,
    }
    return EventIn(
        ts=ts,
        source="gmail",
        type="email.received",
        external_id=external_id,
        actor=sender,
        payload=payload,
        pipeline_ver=PV,
    )


def _store_with_timeline() -> InMemoryEventStore:
    store = InMemoryEventStore()
    store.append(_mail("m1", "Alice <alice@past.com>", datetime(2026, 1, 1, tzinfo=UTC)))
    store.append(_mail("m2", "Bob <bob@mid.com>", datetime(2026, 3, 1, tzinfo=UTC)))
    store.append(_mail("m3", "Carol <carol@future.com>", datetime(2026, 6, 1, tzinfo=UTC)))
    return store


def test_time_filtered_store_cuts_by_ts() -> None:
    store = _store_with_timeline()
    cut = TimeFilteredEventStore(store, until=datetime(2026, 3, 15, tzinfo=UTC))
    ids = [e.external_id for e in cut.all_events()]
    assert ids == ["m1", "m2"]  # m3 (junio) queda fuera
    assert cut.count() == 2


def test_time_filtered_store_is_read_only() -> None:
    store = _store_with_timeline()
    cut = TimeFilteredEventStore(store, until=datetime(2026, 12, 1, tzinfo=UTC))
    with pytest.raises(SimulatorWriteAttempt):
        cut.append(_mail("x", "x@x.com", datetime(2026, 1, 1, tzinfo=UTC)))


def test_snapshot_has_past_facts() -> None:
    store = _store_with_timeline()
    snap = build_snapshot(store, datetime(2026, 3, 15, tzinfo=UTC))
    assert snap.find_entity("person", "alice@past.com") is not None
    assert snap.find_entity("person", "bob@mid.com") is not None


def test_no_temporal_leakage() -> None:
    """CRÍTICO: un hecho de un evento posterior a t NO puede aparecer en t."""
    store = _store_with_timeline()
    snap = build_snapshot(store, datetime(2026, 3, 15, tzinfo=UTC))
    # carol@future.com viene de un mail de junio: NO debe existir en marzo.
    assert snap.find_entity("person", "carol@future.com") is None
    assert snap.find_entity("org", "future.com") is None
    names = [n.lower() for n in snap.entity_names()]
    assert not any("future.com" in n for n in names), "FUGA TEMPORAL: hecho futuro visible en t"


def test_snapshot_at_end_sees_all() -> None:
    store = _store_with_timeline()
    snap = build_snapshot(store, datetime(2026, 12, 1, tzinfo=UTC))
    assert snap.find_entity("person", "carol@future.com") is not None


def test_snapshot_relations_valid_at_excludes_future() -> None:
    """Una relación creada por un evento futuro no está vigente en t."""
    store = _store_with_timeline()
    snap_march = build_snapshot(store, datetime(2026, 3, 15, tzinfo=UTC))
    # La relación person->org de carol (member_of future.com) no existe en marzo.
    for rec in snap_march.graph.entities_all():
        rels = snap_march.relations_valid_at(rec.id)
        for r in rels:
            dst = snap_march.graph.get_entity(r.dst)
            assert dst is None or "future.com" not in dst.name
