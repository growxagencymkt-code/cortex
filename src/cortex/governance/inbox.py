"""Bandeja de decisiones en memoria (SYSTEM_PROMPT §11.2).

Cola de tarjetas por urgencia. Cada tarjeta tiene la anatomía de §11.2:
    título → recomendación resumida → Aprobar/Editar/Rechazar
    → "por qué" colapsado (razonamiento + evidencia cruda: evidence_events).

Tipos de tarjeta (§11.2): propuesta de acción, desambiguación, propuesta de
nuevo agente, alerta de compromiso.

Anti-inercia (§11.2): ~1 de cada 15 tarjetas se presenta SIN recomendación, para
que el humano no apruebe en piloto automático. Acá es determinista: cada 15ª
tarjeta que entraría CON recomendación se muestra sin ella.

Espeja la tabla `decisions_log` (§6) en memoria (DB-agnóstico), igual que
`InMemoryGraph` espeja `entities`/`relations`:
    decisions_log(id BIGSERIAL PK, ts TIMESTAMPTZ, proposal JSONB,
                  evidence_events BIGINT[], human_choice TEXT NOT NULL,
                  human_note TEXT, result_event BIGINT REFERENCES events(id))

Cada elección humana produce (a) una fila en el mirror de `decisions_log` y
(b) un `EventIn` con `source='human_ui'` para que el llamador lo appende al log
de eventos (§11.2: "todo va a decisions_log y como evento source='human_ui'").
Este módulo NO escribe el store de eventos: devuelve el evento a appendear.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cortex.events.models import EventIn

# Cada cuántas tarjetas con recomendación se suprime la recomendación (anti-inercia).
ANTI_INERTIA_EVERY = 15

# Fuente y tipo del evento que genera una decisión humana. 'human_ui' es fuente
# CONFIABLE de instrucción (governance.injection.TRUSTED_INSTRUCTION_SOURCES).
HUMAN_UI_SOURCE = "human_ui"
DECISION_EVENT_TYPE = "human_decision"


class CardKind(str, Enum):
    """Tipos de tarjeta de la bandeja (§11.2)."""

    ACTION_PROPOSAL = "action-proposal"
    DISAMBIGUATION = "disambiguation"
    NEW_AGENT_PROPOSAL = "new-agent-proposal"
    COMMITMENT_ALERT = "commitment-alert"


class HumanChoice(str, Enum):
    """Las tres respuestas posibles del humano (§11.2)."""

    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


class DecisionCard(BaseModel):
    """Una tarjeta en la bandeja. `recommendation is None` → tarjeta anti-inercia
    (o desambiguación pura): el humano decide sin sugerencia previa."""

    model_config = ConfigDict(frozen=True)

    id: int
    kind: CardKind
    title: str
    recommendation: str | None
    reasoning: str
    evidence_events: list[int] = Field(default_factory=list)
    urgency: int = 0
    proposal: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    anti_inertia: bool = False  # True si se suprimió la recomendación por anti-inercia
    resolved: bool = False


class DecisionLogEntry(BaseModel):
    """Fila del mirror de `decisions_log` (§6)."""

    model_config = ConfigDict(frozen=True)

    id: int
    ts: datetime
    proposal: dict[str, Any]
    evidence_events: list[int]
    human_choice: str
    human_note: str | None
    result_event: int | None
    card_id: int


class Resolution(BaseModel):
    """Resultado de resolver una tarjeta: la fila de decisions_log + el evento
    `source='human_ui'` que el llamador debe appendear al log de eventos."""

    model_config = ConfigDict(frozen=True)

    log_entry: DecisionLogEntry
    event: EventIn


class InMemoryDecisionInbox:
    """Bandeja de decisiones en memoria + mirror de `decisions_log`.

    Contrato idéntico al futuro respaldo Postgres (§6): la migración a la base
    es directa. No toca el log de eventos: al resolver, DEVUELVE el `EventIn`
    (`source='human_ui'`) para que el orquestador/llamador lo appende.
    """

    def __init__(self, *, pipeline_ver: str = "0.0.0") -> None:
        self._pipeline_ver = pipeline_ver
        self._cards: dict[int, DecisionCard] = {}
        self._log: list[DecisionLogEntry] = []
        self._card_counter: int = 0
        self._log_counter: int = 0
        # Cuenta tarjetas que ENTRARON con recomendación (base del anti-inercia).
        self._recommended_seen: int = 0

    # --------------------------------------------------------------------- cards
    def add_card(
        self,
        *,
        kind: CardKind,
        title: str,
        reasoning: str,
        recommendation: str | None = None,
        evidence_events: list[int] | None = None,
        urgency: int = 0,
        proposal: dict[str, Any] | None = None,
        created_at: datetime,
    ) -> DecisionCard:
        """Encola una tarjeta. Si trae recomendación, aplica anti-inercia: cada
        `ANTI_INERTIA_EVERY`-ésima tarjeta con recomendación se suprime (se
        presenta sin recomendación para forzar juicio independiente)."""
        self._card_counter += 1
        anti = False
        rec = recommendation
        if recommendation is not None:
            self._recommended_seen += 1
            if self._recommended_seen % ANTI_INERTIA_EVERY == 0:
                rec = None
                anti = True

        card = DecisionCard(
            id=self._card_counter,
            kind=kind,
            title=title,
            recommendation=rec,
            reasoning=reasoning,
            evidence_events=list(evidence_events or []),
            urgency=urgency,
            proposal=dict(proposal or {}),
            created_at=created_at,
            anti_inertia=anti,
        )
        self._cards[card.id] = card
        return card

    def get_card(self, card_id: int) -> DecisionCard | None:
        return self._cards.get(card_id)

    def pending(self) -> list[DecisionCard]:
        """Tarjetas sin resolver, ordenadas por urgencia (desc) y luego por id
        (asc, FIFO ante igual urgencia)."""
        cards = [c for c in self._cards.values() if not c.resolved]
        return sorted(cards, key=lambda c: (-c.urgency, c.id))

    # ---------------------------------------------------------------- resolution
    def resolve(
        self,
        card_id: int,
        choice: HumanChoice,
        *,
        ts: datetime,
        human_note: str | None = None,
        result_event: int | None = None,
        actor: str = "founder",
    ) -> Resolution:
        """Registra la elección humana sobre una tarjeta.

        Produce (a) una fila en el mirror de `decisions_log` y (b) un `EventIn`
        con `source='human_ui'` para que el llamador lo appende al log. Marca la
        tarjeta como resuelta. Idempotencia: resolver dos veces la misma tarjeta
        es un error (ValueError), igual que en la cola real.
        """
        card = self._cards.get(card_id)
        if card is None:
            raise ValueError(f"tarjeta inexistente: {card_id}")
        if card.resolved:
            raise ValueError(f"tarjeta ya resuelta: {card_id}")

        self._log_counter += 1
        log_entry = DecisionLogEntry(
            id=self._log_counter,
            ts=ts,
            proposal=dict(card.proposal),
            evidence_events=list(card.evidence_events),
            human_choice=choice.value,
            human_note=human_note,
            result_event=result_event,
            card_id=card.id,
        )
        self._log.append(log_entry)

        event = EventIn(
            ts=ts,
            source=HUMAN_UI_SOURCE,
            type=DECISION_EVENT_TYPE,
            external_id=None,
            actor=actor,
            payload={
                "card_id": card.id,
                "card_kind": card.kind.value,
                "human_choice": choice.value,
                "human_note": human_note,
                "evidence_events": list(card.evidence_events),
                "proposal": dict(card.proposal),
                "had_recommendation": card.recommendation is not None,
                "anti_inertia": card.anti_inertia,
            },
            pipeline_ver=self._pipeline_ver,
        )

        self._cards[card.id] = card.model_copy(update={"resolved": True})
        return Resolution(log_entry=log_entry, event=event)

    # ----------------------------------------------------------------- accessors
    def decisions_log(self) -> tuple[DecisionLogEntry, ...]:
        """Mirror completo de `decisions_log` (orden de inserción)."""
        return tuple(self._log)
