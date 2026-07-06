"""Clasificación de reversibilidad de acciones (SYSTEM_PROMPT §4, principio 4).

Toda acción de todo agente se etiqueta:
- REVERSIBLE: borradores, análisis, lecturas. Autonomía amplia.
- COSTLY (costosa): mail enviado, invitación creada. Autonomía acotada, auditoría.
- IRREVERSIBLE: pagos, borrados, publicaciones. **Requieren aprobación humana
  explícita SIEMPRE**, sin excepción por madurez del agente (principio 4).

Este módulo es un CONTRATO compartido (lo importan orquestador, agentes,
simulador y la bandeja de decisiones). No ejecuta acciones: las clasifica.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class Reversibility(str, Enum):
    REVERSIBLE = "reversible"
    COSTLY = "costly"
    IRREVERSIBLE = "irreversible"


# Acciones conocidas → su clase de reversibilidad. Conservador: ante la duda,
# se clasifica hacia el lado más restrictivo (ver classify_action).
_ACTION_REVERSIBILITY: dict[str, Reversibility] = {
    # Reversibles
    "draft": Reversibility.REVERSIBLE,
    "analyze": Reversibility.REVERSIBLE,
    "read": Reversibility.REVERSIBLE,
    "summarize": Reversibility.REVERSIBLE,
    "propose": Reversibility.REVERSIBLE,
    "tag": Reversibility.REVERSIBLE,
    # Costosas (efecto en el mundo, pero recuperable / no destructivo)
    "send_email": Reversibility.COSTLY,
    "reply_email": Reversibility.COSTLY,
    "create_event": Reversibility.COSTLY,
    "create_task": Reversibility.COSTLY,
    "post_message": Reversibility.COSTLY,
    # Irreversibles (destructivas / con dinero / públicas)
    "delete": Reversibility.IRREVERSIBLE,
    "pay": Reversibility.IRREVERSIBLE,
    "transfer_funds": Reversibility.IRREVERSIBLE,
    "publish": Reversibility.IRREVERSIBLE,
    "sign_contract": Reversibility.IRREVERSIBLE,
    "grant_access": Reversibility.IRREVERSIBLE,
}


class ActionClassification(BaseModel):
    """Resultado de clasificar una acción propuesta."""

    model_config = ConfigDict(frozen=True)

    action: str
    reversibility: Reversibility
    requires_human_approval: bool
    known: bool  # False si la acción no estaba en el catálogo (default conservador)


def classify_action(action: str) -> ActionClassification:
    """Clasifica una acción por su nombre.

    Regla conservadora: una acción DESCONOCIDA se trata como IRREVERSIBLE (exige
    aprobación humana). Es más seguro pedir permiso de más que ejecutar de más.
    Las irreversibles SIEMPRE requieren aprobación humana (principio 4).
    """
    key = action.strip().lower()
    known = key in _ACTION_REVERSIBILITY
    rev = _ACTION_REVERSIBILITY.get(key, Reversibility.IRREVERSIBLE)
    return ActionClassification(
        action=action,
        reversibility=rev,
        requires_human_approval=(rev is Reversibility.IRREVERSIBLE),
        known=known,
    )
