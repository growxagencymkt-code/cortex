"""Orquestador mínimo: ruteo, autorización de acciones, monitoreo (§4, §10)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cortex.agents.candidates import mail_responder_spec
from cortex.agents.lifecycle import PromotionMetrics
from cortex.agents.specs import AgentSpec, MetricsGate, Stage
from cortex.events.models import EventIn
from cortex.governance.inbox import CardKind
from cortex.orchestrator.router import Orchestrator, ProposedAction


def _t() -> datetime:
    return datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def _event(source: str = "gmail", type_: str = "email_received") -> EventIn:
    return EventIn(
        ts=_t(), source=source, type=type_, external_id=None, actor="ana@x.com",
        payload={"subject": "hola"}, pipeline_ver="0.0.0",
    )


def _agent(stage: Stage, **kw: object) -> AgentSpec:
    kw.setdefault("permissions", {"allowed_actions": ["draft", "reply_email"]})
    return AgentSpec(
        name="mail-responder", version=1, stage=stage, prompt="p",
        triggers=[{"source": "gmail", "type": "email_received"}],
        **kw,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------------- ruteo
def test_route_matches_triggers_on_operational_stage() -> None:
    orch = Orchestrator()
    orch.register(_agent(Stage.PRODUCTION))
    matched = orch.route(_event())
    assert [a.name for a in matched] == ["mail-responder"]


def test_route_ignores_non_operational_stages() -> None:
    orch = Orchestrator()
    orch.register(_agent(Stage.DESIGN))  # design no recibe tráfico real
    orch.register(_agent(Stage.SIMULATION))
    assert orch.route(_event()) == []


def test_route_no_match_on_different_source_or_type() -> None:
    orch = Orchestrator()
    orch.register(_agent(Stage.PRODUCTION))
    assert orch.route(_event(source="calendar")) == []
    assert orch.route(_event(type_="email_sent")) == []


def test_empty_trigger_does_not_match_everything() -> None:
    orch = Orchestrator()
    spec = AgentSpec(name="x", version=1, stage=Stage.PRODUCTION, prompt="p", triggers=[{}])
    orch.register(spec)
    assert orch.route(_event()) == []


# ------------------------------------------------------ acciones: autorización
def test_reversible_action_in_production_becomes_agent_event() -> None:
    orch = Orchestrator()
    orch.register(_agent(Stage.PRODUCTION))
    outcome = orch.submit_action(
        ProposedAction(agent_name="mail-responder", agent_version=1, action="draft"),
        ts=_t(),
    )
    assert outcome.approval_card is None
    assert outcome.agent_event is not None
    assert outcome.agent_event.source == "agent"
    assert outcome.agent_event.actor == "agent:mail-responder:v1"
    assert outcome.agent_event.type == "action.draft"
    # No se encoló nada en la bandeja.
    assert orch.inbox.pending() == []


def test_irreversible_action_always_creates_human_card() -> None:
    orch = Orchestrator()
    orch.register(_agent(Stage.PRODUCTION, permissions={"allowed_actions": ["delete"]}))
    outcome = orch.submit_action(
        ProposedAction(agent_name="mail-responder", agent_version=1, action="delete"),
        ts=_t(),
    )
    assert outcome.agent_event is None
    assert outcome.approval_card is not None
    assert outcome.approval_card.kind is CardKind.ACTION_PROPOSAL
    assert orch.inbox.pending() == [outcome.approval_card]


def test_costly_action_in_canary_escalates_to_card() -> None:
    orch = Orchestrator()
    orch.register(_agent(Stage.CANARY))
    outcome = orch.submit_action(
        ProposedAction(agent_name="mail-responder", agent_version=1, action="reply_email"),
        ts=_t(),
    )
    assert outcome.agent_event is None
    assert outcome.approval_card is not None
    assert outcome.authorization.requires_human_approval is True


def test_reversible_action_in_canary_is_autonomous() -> None:
    orch = Orchestrator()
    orch.register(_agent(Stage.CANARY))
    outcome = orch.submit_action(
        ProposedAction(agent_name="mail-responder", agent_version=1, action="draft"),
        ts=_t(),
    )
    assert outcome.agent_event is not None
    assert outcome.approval_card is None


def test_submit_action_unknown_agent_raises() -> None:
    orch = Orchestrator()
    with pytest.raises(ValueError):
        orch.submit_action(
            ProposedAction(agent_name="ghost", agent_version=9, action="draft"), ts=_t()
        )


# ------------------------------------------------------------- monitoreo/degradar
def test_monitor_healthy_does_not_degrade() -> None:
    orch = Orchestrator()
    spec = _agent(Stage.CANARY, metrics_gate=MetricsGate(dangerous_rate_max=0.0))
    orch.register(spec)
    res = orch.monitor(spec, PromotionMetrics(dangerous_rate=0.0, canary_incidents=0))
    assert res.healthy is True
    assert res.degraded is False
    assert res.spec.stage is Stage.CANARY


def test_monitor_degrades_one_stage_on_danger() -> None:
    orch = Orchestrator()
    spec = _agent(Stage.PRODUCTION)
    orch.register(spec)
    res = orch.monitor(spec, PromotionMetrics(dangerous_rate=0.2))
    assert res.healthy is False
    assert res.degraded is True
    assert res.spec.stage is Stage.CANARY
    # El registro quedó actualizado con el spec degradado.
    updated = orch.get_agent("mail-responder", 1)
    assert updated is not None and updated.stage is Stage.CANARY


def test_monitor_degrades_on_canary_incident() -> None:
    orch = Orchestrator()
    spec = _agent(Stage.CANARY)
    orch.register(spec)
    res = orch.monitor(spec, PromotionMetrics(dangerous_rate=0.0, canary_incidents=1))
    assert res.degraded is True
    assert res.spec.stage is Stage.SHADOW


def test_monitor_at_design_floor_does_not_degrade() -> None:
    orch = Orchestrator()
    spec = _agent(Stage.DESIGN)
    orch.register(spec)
    res = orch.monitor(spec, PromotionMetrics(dangerous_rate=1.0))
    assert res.healthy is False
    assert res.degraded is False
    assert res.spec.stage is Stage.DESIGN


# --------------------------------------------------------- primer candidato F4
def test_mail_responder_candidate_is_design_unapproved_undeployed() -> None:
    spec = mail_responder_spec()
    assert spec.stage is Stage.DESIGN
    assert spec.approved_at is None
    assert spec.is_human_approved() is False
    assert {t.name for t in spec.tools} == {"draft", "reply_email"}
    assert spec.prompt.strip() != ""
    # No es ruteable: en DESIGN no recibe tráfico real.
    orch = Orchestrator()
    orch.register(spec)
    assert orch.route(_event()) == []


def test_mail_responder_prompt_encodes_principle_3() -> None:
    spec = mail_responder_spec()
    # El prompt debe cimentar principio 3 (contenido observado ≠ instrucciones).
    assert "principio 3" in spec.prompt.lower()
