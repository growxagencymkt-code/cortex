"""Ciclo de vida de agentes y compuertas de promoción (SYSTEM_PROMPT §10, principio 5).

Ciclo obligatorio y sin atajos:
    design → simulation → shadow → canary → production → retired

Reglas de oro que este módulo cimenta en código:
- **Promoción SIEMPRE requiere un humano.** `can_promote` sólo dice si las
  compuertas métricas objetivas están satisfechas; el sello final es humano.
- **Degradación automática baja exactamente UNA etapa** (`degrade`), sin humano
  (§10: "baja un stage solo; subir requiere humano").
- **Las acciones irreversibles requieren aprobación humana SIEMPRE**, sin
  excepción por madurez del agente (principio 4). `authorize_action` lo garantiza
  antes de mirar la etapa.

Este módulo es lógica de gobernanza determinista: no llama a modelos ni ejecuta
acciones. Consume los contratos compartidos `AgentSpec`/`Stage` (agents.specs) y
`classify_action`/`Reversibility` (governance.reversibility).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from cortex.agents.specs import STAGE_ORDER, AgentSpec, Stage
from cortex.governance.reversibility import Reversibility, classify_action

# --- Umbrales objetivos del ciclo de vida (§10). No hardcodean datos del fundador. ---
MIN_SIMULATION_CASES = 50
MIN_SHADOW_ACCEPTANCE = 0.70
MIN_SHADOW_WEEKS = 2.0
MIN_CANARY_WEEKS = 2.0
MAX_CANARY_INCIDENTS = 0


class PromotionMetrics(BaseModel):
    """Evidencia medida que alimenta las compuertas de promoción (§9.3, §10).

    Defaults CONSERVADORES: sin evidencia, ninguna compuerta pasa. En particular
    `dangerous_rate` arranca en 1.0 (peligroso hasta demostrar 0) y las tasas de
    aceptación/cobertura en 0.0.
    """

    model_config = ConfigDict(frozen=True)

    # Simulación (§9.3).
    cases_count: int = 0
    agreement_rate: float = 0.0
    coverage_rate: float = 0.0
    dangerous_rate: float = 1.0
    cost_per_case_usd: float | None = None
    # Sombra (§10): % aceptadas sin edición, sostenido en el tiempo.
    shadow_acceptance_rate: float = 0.0
    shadow_weeks: float = 0.0
    # Canario (§10): tiempo sostenido y ausencia de incidentes.
    canary_weeks: float = 0.0
    canary_incidents: int = 0


class PromotionDecision(BaseModel):
    """Resultado de evaluar la promoción de un agente.

    `gates_passed` = las compuertas OBJETIVAS están satisfechas. Aun así,
    `requires_human_approval` es SIEMPRE True para promover: el sistema propone,
    el humano promueve (§10, principio 7)."""

    model_config = ConfigDict(frozen=True)

    from_stage: Stage
    to_stage: Stage | None
    gates_passed: bool
    requires_human_approval: bool = True
    reasons: list[str] = Field(default_factory=list)

    @property
    def can_promote(self) -> bool:
        """Hay una etapa siguiente y sus compuertas objetivas pasan. (El humano
        sigue siendo obligatorio para ejecutar la promoción.)"""
        return self.to_stage is not None and self.gates_passed


class AuthorizationDecision(BaseModel):
    """Veredicto sobre si un agente puede ejecutar una acción por su cuenta AHORA.

    `authorized` True = el agente puede ejecutarla de forma autónoma en su etapa.
    `requires_human_approval` True = necesita pasar por la bandeja de decisiones."""

    model_config = ConfigDict(frozen=True)

    action: str
    stage: Stage
    reversibility: Reversibility
    authorized: bool
    requires_human_approval: bool
    reason: str


def _next_stage(stage: Stage) -> Stage | None:
    """Etapa siguiente en el orden de promoción, o None si no hay (production /
    retired no promueven: el retiro es una acción aparte, no una promoción)."""
    if stage not in STAGE_ORDER:
        return None
    idx = STAGE_ORDER.index(stage)
    if idx + 1 >= len(STAGE_ORDER):
        return None
    return STAGE_ORDER[idx + 1]


def _gate_design_to_simulation(spec: AgentSpec) -> list[str]:
    reasons: list[str] = []
    if spec.is_human_approved():
        reasons.append("OK diseño aprobado por humano (approved_at presente)")
    else:
        reasons.append("BLOQUEO falta aprobación humana del diseño (approved_at)")
    return reasons


def _gate_simulation_to_shadow(spec: AgentSpec, m: PromotionMetrics) -> list[str]:
    gate = spec.metrics_gate
    reasons: list[str] = []
    reasons.append(
        f"{'OK' if m.cases_count >= MIN_SIMULATION_CASES else 'BLOQUEO'} "
        f"casos {m.cases_count} (mín {MIN_SIMULATION_CASES})"
    )
    reasons.append(
        f"{'OK' if m.agreement_rate >= gate.agreement_min else 'BLOQUEO'} "
        f"acuerdo {m.agreement_rate:.2f} (mín {gate.agreement_min:.2f})"
    )
    reasons.append(
        f"{'OK' if m.dangerous_rate <= gate.dangerous_rate_max else 'BLOQUEO'} "
        f"tasa peligrosa {m.dangerous_rate:.3f} (máx {gate.dangerous_rate_max:.3f})"
    )
    reasons.append(
        f"{'OK' if m.coverage_rate >= gate.coverage_min else 'BLOQUEO'} "
        f"cobertura {m.coverage_rate:.2f} (mín {gate.coverage_min:.2f})"
    )
    if gate.cost_per_case_max_usd is None:
        reasons.append("OK costo por caso sin techo definido")
    else:
        ok_cost = m.cost_per_case_usd is not None and m.cost_per_case_usd <= gate.cost_per_case_max_usd
        shown = "n/d" if m.cost_per_case_usd is None else f"{m.cost_per_case_usd:.4f}"
        reasons.append(
            f"{'OK' if ok_cost else 'BLOQUEO'} costo/caso {shown} "
            f"(máx {gate.cost_per_case_max_usd:.4f})"
        )
    return reasons


def _gate_shadow_to_canary(m: PromotionMetrics, gate_dangerous_max: float) -> list[str]:
    reasons: list[str] = []
    reasons.append(
        f"{'OK' if m.shadow_acceptance_rate >= MIN_SHADOW_ACCEPTANCE else 'BLOQUEO'} "
        f"aceptación sin edición {m.shadow_acceptance_rate:.2f} (mín {MIN_SHADOW_ACCEPTANCE:.2f})"
    )
    reasons.append(
        f"{'OK' if m.shadow_weeks >= MIN_SHADOW_WEEKS else 'BLOQUEO'} "
        f"semanas en sombra {m.shadow_weeks:.1f} (mín {MIN_SHADOW_WEEKS:.1f})"
    )
    reasons.append(
        f"{'OK' if m.dangerous_rate <= gate_dangerous_max else 'BLOQUEO'} "
        f"tasa peligrosa sostenida {m.dangerous_rate:.3f} (máx {gate_dangerous_max:.3f})"
    )
    return reasons


def _gate_canary_to_production(m: PromotionMetrics) -> list[str]:
    reasons: list[str] = []
    reasons.append(
        f"{'OK' if m.canary_weeks >= MIN_CANARY_WEEKS else 'BLOQUEO'} "
        f"semanas en canario {m.canary_weeks:.1f} (mín {MIN_CANARY_WEEKS:.1f})"
    )
    reasons.append(
        f"{'OK' if m.canary_incidents <= MAX_CANARY_INCIDENTS else 'BLOQUEO'} "
        f"incidentes en canario {m.canary_incidents} (máx {MAX_CANARY_INCIDENTS})"
    )
    return reasons


def can_promote(spec: AgentSpec, metrics: PromotionMetrics | None = None) -> PromotionDecision:
    """Evalúa si un agente puede promover a la etapa siguiente.

    Devuelve `gates_passed` según las compuertas OBJETIVAS de §10 para la
    transición concreta. La promoción efectiva SIEMPRE requiere un humano
    (`requires_human_approval=True`), pasen o no las compuertas.
    """
    m = metrics if metrics is not None else PromotionMetrics()
    nxt = _next_stage(spec.stage)
    if nxt is None:
        reason = (
            "producción es la última etapa; el retiro es una acción aparte, no una promoción"
            if spec.stage is Stage.PRODUCTION
            else f"{spec.stage.value} no promueve"
        )
        return PromotionDecision(
            from_stage=spec.stage, to_stage=None, gates_passed=False, reasons=[reason]
        )

    if spec.stage is Stage.DESIGN:
        reasons = _gate_design_to_simulation(spec)
    elif spec.stage is Stage.SIMULATION:
        reasons = _gate_simulation_to_shadow(spec, m)
    elif spec.stage is Stage.SHADOW:
        reasons = _gate_shadow_to_canary(m, spec.metrics_gate.dangerous_rate_max)
    elif spec.stage is Stage.CANARY:
        reasons = _gate_canary_to_production(m)
    else:  # pragma: no cover - defensivo; STAGE_ORDER no tiene más casos
        reasons = [f"transición no definida desde {spec.stage.value}"]

    gates_passed = all(not r.startswith("BLOQUEO") for r in reasons)
    return PromotionDecision(
        from_stage=spec.stage, to_stage=nxt, gates_passed=gates_passed, reasons=reasons
    )


def degrade(spec: AgentSpec) -> AgentSpec:
    """Degrada al agente EXACTAMENTE una etapa (automático, sin humano; §10).

    Devuelve una versión nueva del spec una etapa más atrás. En el piso
    (DESIGN) o fuera del orden (RETIRED) es idempotente: devuelve el mismo spec.
    """
    if spec.stage not in STAGE_ORDER:
        return spec
    idx = STAGE_ORDER.index(spec.stage)
    if idx == 0:
        return spec
    prev = STAGE_ORDER[idx - 1]
    return spec.model_copy(update={"stage": prev})


def _action_in_permissions(spec: AgentSpec, action: str) -> bool:
    """True si la acción está dentro del allowlist de permisos del agente.

    Si `permissions["allowed_actions"]` no está definido, no se restringe por
    allowlist (se cae en las reglas de reversibilidad/etapa). Si está definido,
    la acción DEBE figurar (N1 regla dura: fuera de permisos → fallo)."""
    allowed = spec.permissions.get("allowed_actions")
    if allowed is None:
        return True
    if isinstance(allowed, (list, tuple, set, frozenset)):
        return action in {str(a) for a in allowed}
    return False


def _costly_low_risk_in_canary(spec: AgentSpec, action: str) -> bool:
    """En canario sólo se permiten costosas de BAJO RIESGO explícitamente
    marcadas en `permissions["low_risk_actions"]` (§10)."""
    low = spec.permissions.get("low_risk_actions")
    if isinstance(low, (list, tuple, set, frozenset)):
        return action in {str(a) for a in low}
    return False


def authorize_action(spec: AgentSpec, action: str) -> AuthorizationDecision:
    """Decide si el agente puede ejecutar `action` por su cuenta en su etapa.

    Orden de chequeo (de más duro a más blando):
    1. **Fuera de permisos** → nunca autónomo, escala a humano (N1 regla dura).
    2. **Irreversible** → aprobación humana SIEMPRE, sin importar la etapa
       (principio 4). Esta es la regla que ninguna madurez de agente saltea.
    3. Según la etapa, para reversibles/costosas dentro de permisos:
       - production: reversible libre; costosa libre (con auditoría posterior).
       - canary: reversible libre; costosa sólo si es de bajo riesgo declarada.
       - shadow: sólo sugiere → todo va a humano.
       - simulation/design/retired: no ejecutan acciones reales → todo a humano.
    """
    cls = classify_action(action)

    # 1. Allowlist de permisos (regla dura N1).
    if not _action_in_permissions(spec, action):
        return AuthorizationDecision(
            action=action,
            stage=spec.stage,
            reversibility=cls.reversibility,
            authorized=False,
            requires_human_approval=True,
            reason="fuera de permisos del agente (allowed_actions) → escala a humano",
        )

    # 2. Irreversible: SIEMPRE humano (principio 4), sin importar la etapa.
    if cls.reversibility is Reversibility.IRREVERSIBLE:
        detalle = "" if cls.known else " [acción desconocida → tratada como irreversible]"
        return AuthorizationDecision(
            action=action,
            stage=spec.stage,
            reversibility=cls.reversibility,
            authorized=False,
            requires_human_approval=True,
            reason=f"irreversible: aprobación humana SIEMPRE (principio 4){detalle}",
        )

    # 3. Reversible / costosa dentro de permisos: depende de la etapa.
    stage = spec.stage
    if stage is Stage.PRODUCTION:
        nota = "reversible libre" if cls.reversibility is Reversibility.REVERSIBLE else "costosa con auditoría posterior"
        return AuthorizationDecision(
            action=action, stage=stage, reversibility=cls.reversibility,
            authorized=True, requires_human_approval=False, reason=f"producción: {nota}",
        )

    if stage is Stage.CANARY:
        if cls.reversibility is Reversibility.REVERSIBLE:
            return AuthorizationDecision(
                action=action, stage=stage, reversibility=cls.reversibility,
                authorized=True, requires_human_approval=False, reason="canario: reversible libre",
            )
        # costosa
        if _costly_low_risk_in_canary(spec, action):
            return AuthorizationDecision(
                action=action, stage=stage, reversibility=cls.reversibility,
                authorized=True, requires_human_approval=False,
                reason="canario: costosa de bajo riesgo declarada",
            )
        return AuthorizationDecision(
            action=action, stage=stage, reversibility=cls.reversibility,
            authorized=False, requires_human_approval=True,
            reason="canario: costosa no declarada de bajo riesgo → escala a humano",
        )

    if stage is Stage.SHADOW:
        return AuthorizationDecision(
            action=action, stage=stage, reversibility=cls.reversibility,
            authorized=False, requires_human_approval=True,
            reason="sombra: sólo sugiere → toda acción va a humano",
        )

    # simulation / design / retired: sin acciones reales.
    return AuthorizationDecision(
        action=action, stage=stage, reversibility=cls.reversibility,
        authorized=False, requires_human_approval=True,
        reason=f"{stage.value}: no ejecuta acciones reales → escala a humano",
    )
