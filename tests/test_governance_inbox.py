"""Bandeja de decisiones en memoria (§11.2) + mirror de decisions_log (§6)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cortex.governance.inbox import (
    ANTI_INERTIA_EVERY,
    DECISION_EVENT_TYPE,
    HUMAN_UI_SOURCE,
    CardKind,
    HumanChoice,
    InMemoryDecisionInbox,
)
from cortex.governance.injection import is_trusted_instruction_source


def _t(minute: int = 0) -> datetime:
    return datetime(2026, 7, 6, 12, minute, tzinfo=UTC)


def test_add_card_and_pending_ordered_by_urgency_then_id() -> None:
    inbox = InMemoryDecisionInbox()
    a = inbox.add_card(kind=CardKind.ACTION_PROPOSAL, title="a", reasoning="r", urgency=1, created_at=_t())
    b = inbox.add_card(kind=CardKind.COMMITMENT_ALERT, title="b", reasoning="r", urgency=5, created_at=_t())
    c = inbox.add_card(kind=CardKind.ACTION_PROPOSAL, title="c", reasoning="r", urgency=5, created_at=_t())

    order = [card.id for card in inbox.pending()]
    # urgencia desc; ante empate, id asc (FIFO).
    assert order == [b.id, c.id, a.id]


def test_card_carries_full_anatomy() -> None:
    inbox = InMemoryDecisionInbox()
    card = inbox.add_card(
        kind=CardKind.ACTION_PROPOSAL,
        title="Responder a Ana",
        recommendation="enviar borrador",
        reasoning="Ana pidió el reporte el martes",
        evidence_events=[10, 11],
        proposal={"action": "draft"},
        created_at=_t(),
    )
    assert card.recommendation == "enviar borrador"
    assert card.reasoning
    assert card.evidence_events == [10, 11]
    assert card.proposal == {"action": "draft"}


def test_anti_inertia_suppresses_every_15th_recommended_card() -> None:
    inbox = InMemoryDecisionInbox()
    cards = [
        inbox.add_card(
            kind=CardKind.ACTION_PROPOSAL,
            title=f"c{i}",
            recommendation="hacé X",
            reasoning="r",
            created_at=_t(),
        )
        for i in range(ANTI_INERTIA_EVERY)
    ]
    # Las primeras 14 conservan recomendación; la 15ª se presenta sin ella.
    assert all(c.recommendation is not None for c in cards[:-1])
    assert cards[-1].recommendation is None
    assert cards[-1].anti_inertia is True


def test_cards_without_recommendation_do_not_count_toward_anti_inertia() -> None:
    inbox = InMemoryDecisionInbox()
    # Desambiguaciones puras (sin recomendación) no gastan el contador.
    for _ in range(5):
        inbox.add_card(kind=CardKind.DISAMBIGUATION, title="quién", reasoning="r", created_at=_t())
    recommended = [
        inbox.add_card(
            kind=CardKind.ACTION_PROPOSAL, title="x", recommendation="y", reasoning="r", created_at=_t()
        )
        for _ in range(ANTI_INERTIA_EVERY)
    ]
    assert recommended[-1].recommendation is None  # la 15ª CON recomendación


def test_resolve_produces_log_entry_and_human_ui_event() -> None:
    inbox = InMemoryDecisionInbox(pipeline_ver="1.2.3")
    card = inbox.add_card(
        kind=CardKind.ACTION_PROPOSAL,
        title="Responder",
        recommendation="enviar",
        reasoning="r",
        evidence_events=[7],
        proposal={"action": "reply_email"},
        created_at=_t(),
    )
    res = inbox.resolve(card.id, HumanChoice.APPROVE, ts=_t(5), human_note="dale")

    # decisions_log
    assert res.log_entry.human_choice == "approve"
    assert res.log_entry.evidence_events == [7]
    assert res.log_entry.human_note == "dale"
    assert inbox.decisions_log() == (res.log_entry,)

    # evento source='human_ui' (fuente CONFIABLE de instrucción)
    assert res.event.source == HUMAN_UI_SOURCE
    assert res.event.type == DECISION_EVENT_TYPE
    assert res.event.pipeline_ver == "1.2.3"
    assert res.event.payload["human_choice"] == "approve"
    assert res.event.payload["card_id"] == card.id
    assert is_trusted_instruction_source(res.event.source) is True


def test_resolve_marks_card_resolved_and_removes_from_pending() -> None:
    inbox = InMemoryDecisionInbox()
    card = inbox.add_card(kind=CardKind.ACTION_PROPOSAL, title="x", reasoning="r", created_at=_t())
    inbox.resolve(card.id, HumanChoice.REJECT, ts=_t(1))
    assert inbox.pending() == []
    assert inbox.get_card(card.id) is not None
    resolved = inbox.get_card(card.id)
    assert resolved is not None and resolved.resolved is True


def test_resolve_twice_raises() -> None:
    inbox = InMemoryDecisionInbox()
    card = inbox.add_card(kind=CardKind.ACTION_PROPOSAL, title="x", reasoning="r", created_at=_t())
    inbox.resolve(card.id, HumanChoice.APPROVE, ts=_t(1))
    with pytest.raises(ValueError):
        inbox.resolve(card.id, HumanChoice.APPROVE, ts=_t(2))


def test_resolve_unknown_card_raises() -> None:
    inbox = InMemoryDecisionInbox()
    with pytest.raises(ValueError):
        inbox.resolve(999, HumanChoice.APPROVE, ts=_t())


def test_all_card_kinds_supported() -> None:
    inbox = InMemoryDecisionInbox()
    for kind in CardKind:
        card = inbox.add_card(kind=kind, title=kind.value, reasoning="r", created_at=_t())
        assert card.kind is kind
