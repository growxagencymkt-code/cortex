"""Agente bajo prueba: política de decisión que el simulador ejercita (§9.2).

En producción, la conducta del agente la produce un LLM detrás del seam de
inferencia (F4, orquestador). En F3, para simular a costo $0 y de forma
determinista, la conducta se modela como una **política**: una función que, dado
el `AgentContext` (spec + disparador + sandbox), decide qué herramientas usar y
cuál es su acción principal. La MISMA política corre en sim y en prod; sólo
cambia la inyección de herramientas (sandbox vs tools reales), coherente con §9.2.

`escalate_all_policy` es la política por defecto (segura): no actúa, escala todo.
`reference_mail_drafter` es un agente bien comportado: redacta un borrador de
respuesta al remitente del SOBRE (destinatario fundamentado, acción reversible) y
NUNCA obedece instrucciones embebidas en el cuerpo (principio 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from cortex.agents.specs import AgentSpec
from cortex.events.models import Event
from cortex.simulator.sandbox import ProposedAction, Sandbox


@dataclass(frozen=True)
class AgentContext:
    """Todo lo que el agente ve para decidir en un caso."""

    spec: AgentSpec
    trigger: Event
    sandbox: Sandbox


@dataclass(frozen=True)
class AgentDecision:
    """Resultado de la política para un caso.

    - `handled=True` con `action`: el agente manejó el caso (para el juez, la
      acción principal a comparar contra el ground truth).
    - `handled=False`, `action=None`: el agente escaló a un humano (cobertura).
    """

    handled: bool
    action: ProposedAction | None = None
    note: str = ""


# Una política es una función pura sobre el contexto. Usa el sandbox para leer la
# memoria y para PROPONER acciones (que se registran, nunca se ejecutan).
AgentPolicy = Callable[[AgentContext], AgentDecision]


def escalate_all_policy(ctx: AgentContext) -> AgentDecision:
    """Política por defecto: no actúa, escala todo. Nunca peligrosa."""
    _ = ctx
    return AgentDecision(handled=False, action=None, note="escaló a humano")


def reference_mail_drafter(ctx: AgentContext) -> AgentDecision:
    """Agente bien comportado: redacta un borrador de respuesta al remitente.

    - Sólo actúa ante correos entrantes; cualquier otro disparador se escala.
    - El destinatario sale del SOBRE (`from`), jamás del cuerpo → fundamentado.
    - La acción es un `draft` (reversible): no envía nada.
    - No lee el cuerpo como orden: lo trata como dato (principio 3). No reenvía,
      no borra, no transfiere, no revela nada aunque el texto lo pida.
    """
    if ctx.trigger.type != "email.received":
        return AgentDecision(handled=False, action=None, note="tipo no manejado; escala")

    target = ctx.sandbox.reply_target()
    if target is None:
        return AgentDecision(handled=False, action=None, note="sin remitente; escala")

    subject = ctx.sandbox.envelope().get("subject", "")
    result = ctx.sandbox.propose(
        tool="draft_reply",
        kind="draft",
        recipient=target,
        summary=f"Borrador de acuse de recibo para «{subject}»".strip(),
        args={"in_reply_to": subject},
    )
    action = ctx.sandbox.proposed_actions[-1]
    assert result["simulated"] is True  # nunca efecto real
    return AgentDecision(handled=True, action=action, note="borrador redactado")
