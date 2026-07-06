"""Read models de los paneles y de la bandeja de decisiones (SYSTEM_PROMPT §11.2, §11.3).

Funciones planas que devuelven dicts JSON-ables: la web (§11) los lee tal cual.
No mutan nada ni llaman a modelos — proyectan la memoria de grafo (F1) y el
ciclo de vida de agentes (F4) a las cuatro superficies de panel más la cola de
tarjetas de la bandeja. Deterministas: misma memoria → misma salida.

Paneles (§11.3):
- Mapa operativo (as-is / to-be).
- Panel de agentes (etapa + 4 métricas + costo + propuesta de promoción).
- Panel de compromisos (vigentes / en riesgo / incumplidos, en dos direcciones).
- Panel de economía (costo vs ahorro estimado).

Bandeja (§11.2): `build_decision_inbox` puebla una `InMemoryDecisionInbox` con
una alerta de compromiso por vencimiento próximo/vencido y una desambiguación por
cada ítem pendiente de la cola. `card_to_api` serializa una tarjeta al contrato
que consume la web.

Este módulo CONSUME contratos compartidos (memory.build, agents.specs,
agents.lifecycle, governance.inbox); no redefine ninguno.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from cortex.agents.lifecycle import PromotionMetrics, can_promote
from cortex.agents.specs import AgentSpec
from cortex.governance.inbox import (
    CardKind,
    DecisionCard,
    InMemoryDecisionInbox,
)
from cortex.memory.build import COMMITMENT_KIND, BuildResult

# Ventana por defecto para marcar un compromiso "en riesgo" (§11.3). Un
# compromiso con fecha que vence dentro de esta ventana entra a `en_riesgo`.
DEFAULT_RISK_DAYS = 3

# Direcciones canónicas de un compromiso (§11.3: "en dos direcciones"). Cualquier
# otro valor se normaliza a `unknown` para no perder el compromiso del panel.
_DIRECTIONS: tuple[str, ...] = ("owed_by_me", "owed_to_me", "unknown")

# Urgencias de las tarjetas de la bandeja (§11.2: cola por urgencia).
_URGENCY_OVERDUE = 90
_URGENCY_AT_RISK = 60
_URGENCY_DISAMBIGUATION = 20

# Mapeo de tipos de tarjeta al contrato de la web (web/src/api/types.ts).
_KIND_TO_API: dict[CardKind, str] = {
    CardKind.ACTION_PROPOSAL: "action",
    CardKind.DISAMBIGUATION: "disambiguation",
    CardKind.NEW_AGENT_PROPOSAL: "new_agent",
    CardKind.COMMITMENT_ALERT: "commitment_alert",
}


# --------------------------------------------------------------------------- helpers
def _normalize_direction(raw: object) -> str:
    """Normaliza la dirección de un compromiso a una de `_DIRECTIONS`."""
    return raw if isinstance(raw, str) and raw in _DIRECTIONS else "unknown"


def _parse_due(raw: object) -> date | None:
    """Parsea el `due` (ISO date str | None) a `date`, o None si no tiene fecha."""
    if isinstance(raw, str) and raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _classify_commitment(due: date | None, today: date, risk_days: int) -> str:
    """Clasifica un compromiso en vigentes / en_riesgo / incumplidos.

    Sólo los compromisos con fecha pueden estar en riesgo o incumplidos
    (principio 2: no inventamos vencimientos). Un compromiso sin fecha es
    siempre `vigentes`."""
    if due is None:
        return "vigentes"
    if due < today:
        return "incumplidos"
    if due <= today + timedelta(days=risk_days):
        return "en_riesgo"
    return "vigentes"


def _empty_group() -> dict[str, list[dict[str, Any]]]:
    return {direction: [] for direction in _DIRECTIONS}


# --------------------------------------------------------------------------- §11.3 panels
def commitments_panel(
    memory: BuildResult, *, now: datetime, risk_days: int = DEFAULT_RISK_DAYS
) -> dict[str, Any]:
    """Panel de compromisos (§11.3): vigentes / en riesgo / incumplidos, en dos
    direcciones (`owed_by_me` / `owed_to_me` / `unknown`).

    Agrupa las entidades `commitment` del grafo. Un compromiso vence "en riesgo"
    si su fecha cae dentro de `risk_days` desde `now`; "incumplido" si su fecha ya
    pasó; los sin fecha quedan en `vigentes`. Cada ítem trae su `evidence_event`
    (el `first_seen_event` de la entidad) para trazabilidad."""
    today = now.date()
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {
        "vigentes": _empty_group(),
        "en_riesgo": _empty_group(),
        "incumplidos": _empty_group(),
    }

    for rec in memory.graph.entities_by_kind(COMMITMENT_KIND):
        due = _parse_due(rec.attrs.get("due"))
        direction = _normalize_direction(rec.attrs.get("direction"))
        group = _classify_commitment(due, today, risk_days)
        item: dict[str, Any] = {
            "what": rec.attrs.get("what"),
            "due": due.isoformat() if due is not None else None,
            "direction": direction,
            "confidence": rec.attrs.get("confidence"),
            "evidence_event": rec.first_seen_event,
        }
        groups[group][direction].append(item)

    counts: dict[str, Any] = {}
    grand_total = 0
    for group_name, by_dir in groups.items():
        group_total = 0
        per_dir: dict[str, int] = {}
        for direction in _DIRECTIONS:
            n = len(by_dir[direction])
            per_dir[direction] = n
            group_total += n
        per_dir["total"] = group_total
        counts[group_name] = per_dir
        grand_total += group_total
    counts["total"] = grand_total

    return {
        "vigentes": groups["vigentes"],
        "en_riesgo": groups["en_riesgo"],
        "incumplidos": groups["incumplidos"],
        "counts": counts,
    }


def agents_panel(
    agents: list[AgentSpec], *, metrics: dict[str, PromotionMetrics] | None = None
) -> dict[str, Any]:
    """Panel de agentes (§11.3): por cada agente su etapa, 4 métricas, costo y la
    propuesta de promoción (compuertas objetivas + sello humano requerido).

    `metrics` mapea nombre de agente → métricas medidas; si un agente no tiene
    métricas se usa `PromotionMetrics()` por defecto (conservador: nada pasa)."""
    metrics_by_name = metrics or {}
    rows: list[dict[str, Any]] = []

    for spec in agents:
        m = metrics_by_name.get(spec.name, PromotionMetrics())
        decision = can_promote(spec, m)
        rows.append(
            {
                "name": spec.name,
                "version": spec.version,
                "stage": spec.stage.value,
                "metrics": {
                    "agreement": m.agreement_rate,
                    "coverage": m.coverage_rate,
                    "dangerous_rate": m.dangerous_rate,
                    "cost_per_case": m.cost_per_case_usd,
                },
                "promotion": {
                    "to_stage": decision.to_stage.value if decision.to_stage is not None else None,
                    "gates_passed": decision.gates_passed,
                    "requires_human_approval": decision.requires_human_approval,
                    "reasons": list(decision.reasons),
                },
            }
        )

    return {"agents": rows, "count": len(rows)}


def economy_panel(
    *, llm_cost_usd: float = 0.0, savings_estimate_usd: float = 0.0
) -> dict[str, Any]:
    """Panel de economía (§11.3): costo (LLM + operación) vs ahorro estimado.

    Función pura: la API le pasa números reales cuando existan. `ratio` es el
    retorno (ahorro / costo), protegido contra división por cero (None si el
    costo es 0)."""
    net = savings_estimate_usd - llm_cost_usd
    ratio = savings_estimate_usd / llm_cost_usd if llm_cost_usd > 0 else None
    return {
        "cost_usd": llm_cost_usd,
        "savings_estimate_usd": savings_estimate_usd,
        "net": net,
        "ratio": ratio,
    }


def operative_map_panel(memory: BuildResult) -> dict[str, Any]:
    """Mapa operativo (§11.3): as-is derivado del grafo (conteo de entidades por
    tipo y de relaciones por tipo). `to_be` queda vacío hasta que se infieran
    procesos (F posterior; principio 2: no inventamos el to-be)."""
    entities_by_kind: dict[str, int] = {}
    for rec in memory.graph.entities_all():
        entities_by_kind[rec.kind] = entities_by_kind.get(rec.kind, 0) + 1

    relations_by_rel: dict[str, int] = {}
    for rel in memory.graph.all_relations():
        relations_by_rel[rel.rel] = relations_by_rel.get(rel.rel, 0) + 1

    return {
        "as_is": {
            "entities_by_kind": entities_by_kind,
            "relations_by_rel": relations_by_rel,
            "entity_total": sum(entities_by_kind.values()),
            "relation_total": sum(relations_by_rel.values()),
        },
        "to_be": {},
    }


# --------------------------------------------------------------------------- §11.2 inbox
def build_decision_inbox(
    memory: BuildResult, *, now: datetime, pipeline_ver: str = "0.0.0"
) -> InMemoryDecisionInbox:
    """Puebla la bandeja de decisiones (§11.2) desde la memoria.

    - Una tarjeta **commitment-alert** por cada compromiso próximo a vencer o ya
      vencido (con recomendación de seguirlo, razonamiento, evidencia y urgencia
      mayor para los vencidos).
    - Una tarjeta **disambiguation** por cada ítem pendiente en la cola, SIN
      recomendación (`recommendation=None`): es juicio humano puro.

    Devuelve la bandeja lista para que la API/web la lea. El anti-inercia de la
    propia bandeja se aplica automáticamente al agregar tarjetas con recomendación.
    """
    inbox = InMemoryDecisionInbox(pipeline_ver=pipeline_ver)
    today = now.date()

    # Alertas de compromiso: primero los vencidos (mayor urgencia), luego los en
    # riesgo. Orden determinista por fecha y por what.
    alerts: list[tuple[int, date, dict[str, Any]]] = []
    for rec in memory.graph.entities_by_kind(COMMITMENT_KIND):
        due = _parse_due(rec.attrs.get("due"))
        if due is None:
            continue
        group = _classify_commitment(due, today, DEFAULT_RISK_DAYS)
        if group == "vigentes":
            continue  # sin fecha próxima: no genera alerta
        overdue = group == "incumplidos"
        urgency = _URGENCY_OVERDUE if overdue else _URGENCY_AT_RISK
        what = rec.attrs.get("what")
        what_str = what if isinstance(what, str) else str(what)
        direction = _normalize_direction(rec.attrs.get("direction"))
        estado = "vencido" if overdue else "próximo a vencer"
        payload: dict[str, Any] = {
            "what": what_str,
            "due": due.isoformat(),
            "direction": direction,
            "state": "overdue" if overdue else "at_risk",
        }
        alerts.append(
            (
                -urgency,  # orden: mayor urgencia primero
                due,
                {
                    "title": f"Compromiso {estado}: {what_str}",
                    "recommendation": f"Seguir el compromiso: {what_str}",
                    "reasoning": (
                        f"El compromiso «{what_str}» vence el {due.isoformat()} "
                        f"({estado}). Dirección: {direction}. "
                        f"Evidencia: evento {rec.first_seen_event}."
                    ),
                    "evidence_events": [rec.first_seen_event],
                    "urgency": urgency,
                    "proposal": payload,
                },
            )
        )

    for _, _, card_kwargs in sorted(alerts, key=lambda a: (a[0], a[1], a[2]["title"])):
        inbox.add_card(
            kind=CardKind.COMMITMENT_ALERT,
            title=card_kwargs["title"],
            recommendation=card_kwargs["recommendation"],
            reasoning=card_kwargs["reasoning"],
            evidence_events=card_kwargs["evidence_events"],
            urgency=card_kwargs["urgency"],
            proposal=card_kwargs["proposal"],
            created_at=now,
        )

    # Desambiguaciones pendientes: juicio humano puro, sin recomendación (§11.2).
    for item in memory.disambiguation_queue.pending():
        n_candidates = len(item.candidates)
        inbox.add_card(
            kind=CardKind.DISAMBIGUATION,
            title=item.question,
            recommendation=None,
            reasoning=(
                f"Hay {n_candidates} candidato(s) para «{item.extracted.name}» "
                f"de tipo '{item.extracted.kind}' y ninguno supera el umbral de "
                f"confianza. Requiere tu criterio."
            ),
            evidence_events=[],
            urgency=_URGENCY_DISAMBIGUATION,
            proposal={
                "name": item.extracted.name,
                "kind": item.extracted.kind,
                "candidates": [str(c) for c in item.candidates],
            },
            created_at=now,
        )

    return inbox


def card_to_api(card: DecisionCard) -> dict[str, Any]:
    """Serializa una tarjeta al contrato que consume la web (web/src/api/types.ts).

    `recommendation` es siempre string: para las tarjetas sin recomendación
    (anti-inercia o desambiguación) se entrega "" (la web detecta el vacío)."""
    return {
        "id": str(card.id),
        "kind": _KIND_TO_API.get(card.kind, card.kind.value),
        "title": card.title,
        "recommendation": card.recommendation or "",
        "why": card.reasoning,
        "evidence_events": list(card.evidence_events),
        "urgency": card.urgency,
        "anti_inertia": card.anti_inertia,
    }
