"""Ciclo de vida y compuertas de promoción/autorización (§10, principio 4/5)."""

from __future__ import annotations

from datetime import UTC, datetime

from cortex.agents.lifecycle import (
    PromotionMetrics,
    authorize_action,
    can_promote,
    degrade,
)
from cortex.agents.specs import AgentSpec, MetricsGate, Stage


def _t() -> datetime:
    return datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def _spec(stage: Stage, *, approved: bool = False, **kw: object) -> AgentSpec:
    return AgentSpec(
        name="mail-responder",
        version=1,
        stage=stage,
        prompt="p",
        approved_at=_t() if approved else None,
        **kw,  # type: ignore[arg-type]
    )


# --------------------------------------------------------- promoción: compuertas
def test_design_to_simulation_needs_human_approval() -> None:
    blocked = can_promote(_spec(Stage.DESIGN, approved=False))
    assert blocked.to_stage is Stage.SIMULATION
    assert blocked.gates_passed is False
    assert blocked.can_promote is False

    ok = can_promote(_spec(Stage.DESIGN, approved=True))
    assert ok.gates_passed is True
    assert ok.can_promote is True


def test_promotion_always_requires_human_even_when_gates_pass() -> None:
    ok = can_promote(_spec(Stage.DESIGN, approved=True))
    assert ok.gates_passed is True
    # La compuerta objetiva pasa, pero promover SIEMPRE necesita un humano.
    assert ok.requires_human_approval is True


def test_simulation_to_shadow_gate() -> None:
    spec = _spec(Stage.SIMULATION, metrics_gate=MetricsGate(cost_per_case_max_usd=0.05))
    good = PromotionMetrics(
        cases_count=50, agreement_rate=0.85, coverage_rate=0.0,
        dangerous_rate=0.0, cost_per_case_usd=0.04,
    )
    assert can_promote(spec, good).gates_passed is True

    # Un solo caso peligroso rompe la compuerta (tasa peligrosa DEBE ser 0).
    dangerous = good.model_copy(update={"dangerous_rate": 0.01})
    assert can_promote(spec, dangerous).gates_passed is False

    # Pocos casos rompe la compuerta.
    few = good.model_copy(update={"cases_count": 49})
    assert can_promote(spec, few).gates_passed is False

    # Costo por encima del techo rompe la compuerta.
    pricey = good.model_copy(update={"cost_per_case_usd": 0.10})
    assert can_promote(spec, pricey).gates_passed is False


def test_shadow_to_canary_gate() -> None:
    spec = _spec(Stage.SHADOW)
    good = PromotionMetrics(shadow_acceptance_rate=0.72, shadow_weeks=2.0, dangerous_rate=0.0)
    assert can_promote(spec, good).gates_passed is True
    assert can_promote(spec, good.model_copy(update={"shadow_acceptance_rate": 0.69})).gates_passed is False
    assert can_promote(spec, good.model_copy(update={"shadow_weeks": 1.0})).gates_passed is False


def test_canary_to_production_gate() -> None:
    spec = _spec(Stage.CANARY)
    good = PromotionMetrics(canary_weeks=2.0, canary_incidents=0)
    assert can_promote(spec, good).gates_passed is True
    assert can_promote(spec, good.model_copy(update={"canary_incidents": 1})).gates_passed is False
    assert can_promote(spec, good.model_copy(update={"canary_weeks": 1.5})).gates_passed is False


def test_production_does_not_promote() -> None:
    d = can_promote(_spec(Stage.PRODUCTION))
    assert d.to_stage is None
    assert d.can_promote is False


def test_no_metrics_defaults_block_everything_conservatively() -> None:
    # Sin métricas, las compuertas de datos no pasan (defaults conservadores).
    assert can_promote(_spec(Stage.SIMULATION)).gates_passed is False
    assert can_promote(_spec(Stage.SHADOW)).gates_passed is False
    assert can_promote(_spec(Stage.CANARY)).gates_passed is False


# ------------------------------------------------------------------- degradación
def test_degrade_drops_exactly_one_stage() -> None:
    assert degrade(_spec(Stage.PRODUCTION)).stage is Stage.CANARY
    assert degrade(_spec(Stage.CANARY)).stage is Stage.SHADOW
    assert degrade(_spec(Stage.SHADOW)).stage is Stage.SIMULATION
    assert degrade(_spec(Stage.SIMULATION)).stage is Stage.DESIGN


def test_degrade_floor_at_design_is_idempotent() -> None:
    s = _spec(Stage.DESIGN)
    assert degrade(s).stage is Stage.DESIGN


def test_degrade_retired_is_noop() -> None:
    s = _spec(Stage.RETIRED)
    assert degrade(s).stage is Stage.RETIRED


def test_degrade_returns_new_spec_not_mutation() -> None:
    s = _spec(Stage.CANARY)
    lowered = degrade(s)
    assert s.stage is Stage.CANARY  # original intacto (frozen)
    assert lowered is not s


# --------------------------------------------------- autorización de acciones
def test_irreversible_always_needs_human_even_in_production() -> None:
    spec = _spec(Stage.PRODUCTION, permissions={"allowed_actions": ["pay", "delete", "publish"]})
    for action in ("pay", "delete", "publish"):
        d = authorize_action(spec, action)
        assert d.authorized is False
        assert d.requires_human_approval is True


def test_unknown_action_treated_as_irreversible() -> None:
    spec = _spec(Stage.PRODUCTION)  # sin allowlist → no restringe por permisos
    d = authorize_action(spec, "frobnicate")
    assert d.requires_human_approval is True
    assert d.authorized is False


def test_out_of_permissions_escalates() -> None:
    spec = _spec(Stage.PRODUCTION, permissions={"allowed_actions": ["draft"]})
    d = authorize_action(spec, "reply_email")  # no está en allowlist
    assert d.authorized is False
    assert "permisos" in d.reason


def test_production_reversible_and_costly_are_autonomous() -> None:
    spec = _spec(Stage.PRODUCTION, permissions={"allowed_actions": ["draft", "reply_email"]})
    assert authorize_action(spec, "draft").authorized is True
    costly = authorize_action(spec, "reply_email")
    assert costly.authorized is True
    assert costly.requires_human_approval is False


def test_canary_reversible_auto_costly_needs_human_unless_low_risk() -> None:
    spec = _spec(
        Stage.CANARY,
        permissions={"allowed_actions": ["draft", "reply_email"], "low_risk_actions": []},
    )
    assert authorize_action(spec, "draft").authorized is True
    assert authorize_action(spec, "reply_email").requires_human_approval is True

    low = _spec(
        Stage.CANARY,
        permissions={"allowed_actions": ["reply_email"], "low_risk_actions": ["reply_email"]},
    )
    assert authorize_action(low, "reply_email").authorized is True


def test_shadow_only_suggests_everything_to_human() -> None:
    spec = _spec(Stage.SHADOW, permissions={"allowed_actions": ["draft", "reply_email"]})
    assert authorize_action(spec, "draft").requires_human_approval is True
    assert authorize_action(spec, "reply_email").requires_human_approval is True


def test_design_and_simulation_do_not_execute_real_actions() -> None:
    for stage in (Stage.DESIGN, Stage.SIMULATION):
        spec = _spec(stage, permissions={"allowed_actions": ["draft"]})
        assert authorize_action(spec, "draft").authorized is False
