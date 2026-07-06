"""Primer candidato de agente: mail-responder (SYSTEM_PROMPT §13 F3/F4).

Construye el `AgentSpec` del redactor de respuestas de mail en etapa DESIGN, sin
aprobar y sin desplegar: es sólo spec + prompt, no corre. El prompt vive en un
archivo versionado (§12: ningún prompt inline) bajo `prompts/`.

Camino de vida (§10): al aprobarlo un humano (`approved_at`) pasa la compuerta
design→simulation; recién ahí el simulador lo mide contra el histórico.
"""

from __future__ import annotations

from pathlib import Path

from cortex.agents.specs import AgentSpec, MetricsGate, Stage, ToolSpec

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# Nombre canónico del agente y su versión de prompt.
MAIL_RESPONDER_NAME = "mail-responder"
MAIL_RESPONDER_VERSION = 1


def load_prompt(name: str, version: int) -> str:
    """Lee un prompt versionado de `prompts/{name}.v{version}.md`.

    Lanza FileNotFoundError si no existe (un agente sin prompt no es un agente)."""
    path = _PROMPTS_DIR / f"{name}.v{version}.md"
    return path.read_text(encoding="utf-8")


def mail_responder_spec() -> AgentSpec:
    """AgentSpec del mail-responder v1 en DESIGN, NO aprobado, NO desplegado.

    - tools: `draft` (reversible) y `reply_email` (costosa).
    - triggers: correos entrantes de Gmail.
    - permissions: allowlist de acciones; sin costosas de bajo riesgo en canario
      (reply_email escala a humano hasta producción).
    - metrics_gate: compuerta de simulación con techo de costo por caso.
    """
    prompt = load_prompt(MAIL_RESPONDER_NAME, MAIL_RESPONDER_VERSION)
    return AgentSpec(
        name=MAIL_RESPONDER_NAME,
        version=MAIL_RESPONDER_VERSION,
        stage=Stage.DESIGN,
        prompt=prompt,
        tools=[
            ToolSpec(
                name="draft",
                description="Redacta un borrador de respuesta (no envía).",
                reversibility="reversible",
            ),
            ToolSpec(
                name="reply_email",
                description="Envía una respuesta al remitente.",
                reversibility="costly",
            ),
        ],
        triggers=[{"source": "gmail", "type": "email_received"}],
        permissions={
            "allowed_actions": ["draft", "reply_email"],
            # Sin costosas de bajo riesgo declaradas: reply_email va a humano en
            # canario y sólo es libre en producción (con auditoría posterior).
            "low_risk_actions": [],
        },
        metrics_gate=MetricsGate(
            agreement_min=0.80,
            dangerous_rate_max=0.0,
            coverage_min=0.0,
            cost_per_case_max_usd=0.05,
        ),
        created_by="founder",
        approved_at=None,  # aún no aprobado: no puede entrar a simulación.
    )
