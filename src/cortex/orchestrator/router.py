"""Orquestador mínimo (SYSTEM_PROMPT §4, §10).

Responsabilidad del orquestador: **instancia, rutea, monitorea y degrada** agentes;
NO los diseña (eso es el núcleo cognitivo). Acá, en F4:

1. **Ruteo por disparadores:** un evento se rutea a los agentes cuyos `triggers`
   (source/type) coinciden con el evento.
2. **Clasificación de reversibilidad:** cada acción propuesta por un agente se
   clasifica y se decide su autorización (`authorize_action`). Las **irreversibles
   requieren tarjeta de aprobación humana SIEMPRE** (principio 4), sin importar la
   etapa del agente.
3. **Acciones de agente = eventos:** una acción autorizada de forma autónoma se
   materializa como un `EventIn` con `source='agent'` que vuelve al log (§10).
4. **Monitoreo/degradación:** hook que baja al agente exactamente una etapa
   (`degrade`) ante señales de salud malas (tasa peligrosa o incidentes).

El orquestador NO ejecuta efectos reales ni llama a modelos: decide y produce
eventos/tarjetas para que otras capas los materialicen. Sólo rutea a agentes en
etapas operativas (shadow→production); design/simulation/retired no reciben tráfico
real.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cortex.agents.lifecycle import (
    AuthorizationDecision,
    PromotionMetrics,
    authorize_action,
    degrade,
)
from cortex.agents.specs import AgentSpec, Stage
from cortex.events.models import EventIn
from cortex.governance.inbox import CardKind, DecisionCard, InMemoryDecisionInbox

# Etapas que reciben tráfico real de ruteo (§10). En design/simulation el agente
# vive en el simulador; retired está apagado.
OPERATIONAL_STAGES: frozenset[Stage] = frozenset(
    {Stage.SHADOW, Stage.CANARY, Stage.PRODUCTION}
)

AGENT_EVENT_SOURCE = "agent"


def _trigger_matches(trigger: dict[str, str], event: EventIn) -> bool:
    """Un disparador coincide si sus claves reconocidas (source/type) igualan al
    evento. Un disparador vacío o sin claves reconocidas NO coincide (no se
    dispara a todo por accidente)."""
    keys = {k for k in ("source", "type") if k in trigger}
    if not keys:
        return False
    if "source" in keys and trigger["source"] != event.source:
        return False
    if "type" in keys and trigger["type"] != event.type:
        return False
    return True


class ProposedAction(BaseModel):
    """Acción que un agente propone ejecutar como consecuencia de un evento.

    El orquestador la clasifica y decide si se autoriza (autónoma) o si escala a
    la bandeja (humano). Nunca se ejecuta acá."""

    model_config = ConfigDict(frozen=True)

    agent_name: str
    agent_version: int
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""
    evidence_events: list[int] = Field(default_factory=list)
    urgency: int = 0


class ActionOutcome(BaseModel):
    """Resultado de procesar una acción propuesta.

    - `authorization`: el veredicto (etapa + reversibilidad + autorizado).
    - `agent_event`: presente si se autorizó de forma autónoma → acción como
      evento `source='agent'` para appendear al log.
    - `approval_card`: presente si necesita humano → tarjeta ya encolada en la
      bandeja (action-proposal). Las dos nunca están presentes a la vez.
    """

    model_config = ConfigDict(frozen=True)

    authorization: AuthorizationDecision
    agent_event: EventIn | None = None
    approval_card: DecisionCard | None = None


class MonitorResult(BaseModel):
    """Resultado del hook de monitoreo. Si `degraded` es True, `spec` es el spec
    ya bajado una etapa (§10: degradación automática, sin humano)."""

    model_config = ConfigDict(frozen=True)

    healthy: bool
    degraded: bool
    spec: AgentSpec
    reason: str


class Orchestrator:
    """Orquestador mínimo en memoria. Registra specs, rutea eventos, procesa
    acciones propuestas y monitorea salud. La bandeja se inyecta (composición)."""

    def __init__(
        self, *, inbox: InMemoryDecisionInbox | None = None, pipeline_ver: str = "0.0.0"
    ) -> None:
        self._pipeline_ver = pipeline_ver
        self.inbox = inbox if inbox is not None else InMemoryDecisionInbox(pipeline_ver=pipeline_ver)
        # Registro por (name, version).
        self._agents: dict[tuple[str, int], AgentSpec] = {}

    # ------------------------------------------------------------------ registro
    def register(self, spec: AgentSpec) -> None:
        """Registra (o reemplaza) un spec por (name, version)."""
        self._agents[(spec.name, spec.version)] = spec

    def agents(self) -> list[AgentSpec]:
        return list(self._agents.values())

    def get_agent(self, name: str, version: int) -> AgentSpec | None:
        return self._agents.get((name, version))

    # -------------------------------------------------------------------- ruteo
    def route(self, event: EventIn) -> list[AgentSpec]:
        """Devuelve los agentes en etapa operativa cuyos `triggers` coinciden con
        el evento. Determinista: orden de registro."""
        matched: list[AgentSpec] = []
        for spec in self._agents.values():
            if spec.stage not in OPERATIONAL_STAGES:
                continue
            if any(_trigger_matches(t, event) for t in spec.triggers):
                matched.append(spec)
        return matched

    # ------------------------------------------------------- acciones propuestas
    def submit_action(self, proposed: ProposedAction, *, ts: datetime) -> ActionOutcome:
        """Clasifica y decide una acción propuesta por un agente registrado.

        - Autorizada (autónoma) → materializa un `EventIn` `source='agent'`.
        - Requiere humano (incluye SIEMPRE las irreversibles, principio 4) →
          encola una tarjeta `action-proposal` en la bandeja.
        """
        spec = self._agents.get((proposed.agent_name, proposed.agent_version))
        if spec is None:
            raise ValueError(
                f"agente no registrado: {proposed.agent_name} v{proposed.agent_version}"
            )

        decision = authorize_action(spec, proposed.action)

        if decision.authorized and not decision.requires_human_approval:
            event = self._build_agent_event(spec, proposed, ts=ts)
            return ActionOutcome(authorization=decision, agent_event=event)

        card = self.inbox.add_card(
            kind=CardKind.ACTION_PROPOSAL,
            title=f"{spec.name} v{spec.version}: {proposed.action}",
            recommendation=f"{proposed.action} — {decision.reason}",
            reasoning=proposed.reasoning or decision.reason,
            evidence_events=proposed.evidence_events,
            urgency=proposed.urgency,
            proposal={
                "agent_name": spec.name,
                "agent_version": spec.version,
                "action": proposed.action,
                "params": dict(proposed.params),
                "reversibility": decision.reversibility.value,
                "stage": spec.stage.value,
            },
            created_at=ts,
        )
        return ActionOutcome(authorization=decision, approval_card=card)

    def _build_agent_event(
        self, spec: AgentSpec, proposed: ProposedAction, *, ts: datetime
    ) -> EventIn:
        """Materializa una acción autorizada como evento `source='agent'` (§10)."""
        return EventIn(
            ts=ts,
            source=AGENT_EVENT_SOURCE,
            type=f"action.{proposed.action}",
            external_id=None,
            actor=f"agent:{spec.name}:v{spec.version}",
            payload={
                "action": proposed.action,
                "params": dict(proposed.params),
                "reasoning": proposed.reasoning,
                "reversibility": authorize_action(spec, proposed.action).reversibility.value,
                "evidence_events": list(proposed.evidence_events),
            },
            pipeline_ver=self._pipeline_ver,
        )

    # -------------------------------------------------------- monitoreo/degradar
    def monitor(self, spec: AgentSpec, metrics: PromotionMetrics) -> MonitorResult:
        """Hook de salud. Degrada UNA etapa (automático) si la señal es mala:
        tasa peligrosa por encima del techo del gate, o incidentes en canario.

        Al degradar, actualiza el registro con el nuevo spec y lo devuelve."""
        gate = spec.metrics_gate
        unhealthy_reasons: list[str] = []
        if metrics.dangerous_rate > gate.dangerous_rate_max:
            unhealthy_reasons.append(
                f"tasa peligrosa {metrics.dangerous_rate:.3f} > máx {gate.dangerous_rate_max:.3f}"
            )
        if metrics.canary_incidents > 0:
            unhealthy_reasons.append(f"{metrics.canary_incidents} incidente(s)")

        if not unhealthy_reasons:
            return MonitorResult(healthy=True, degraded=False, spec=spec, reason="OK salud nominal")

        lowered = degrade(spec)
        degraded = lowered.stage is not spec.stage
        if degraded:
            # Reemplaza en el registro (misma clave name/version).
            self._agents[(lowered.name, lowered.version)] = lowered
        reason = "; ".join(unhealthy_reasons)
        reason += " → degradado" if degraded else " → ya en el piso (design), sin degradar"
        return MonitorResult(healthy=False, degraded=degraded, spec=lowered, reason=reason)
