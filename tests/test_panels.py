"""Read models de paneles y bandeja (§11.2, §11.3): proyección de la memoria.

Construye una `BuildResult` real ingiriendo el corpus de mail de ejemplo y
verifica que los paneles agrupan/proyectan correctamente y que la bandeja se
puebla con tarjetas trazables (evidencia) que serializan al contrato de la web.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from cortex.agents.candidates import mail_responder_spec
from cortex.agents.lifecycle import PromotionMetrics
from cortex.agents.specs import Stage
from cortex.connectors.base import ingest
from cortex.connectors.fixture import FixtureMailConnector
from cortex.events.store import InMemoryEventStore
from cortex.governance.inbox import CardKind
from cortex.memory.build import COMMITMENT_KIND, BuildResult, build_memory
from cortex.orchestrator.panels import (
    agents_panel,
    build_decision_inbox,
    card_to_api,
    commitments_panel,
    economy_panel,
    operative_map_panel,
)

_CORPUS = Path(__file__).parent / "fixtures" / "sample_emails.jsonl"

# Referencia temporal: 6/7/2026. Contra el corpus deja compromisos vencidos
# (abril–junio y 03/07), en riesgo (07/07, 08/07) y sin fecha (vigentes).
_NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def _memory() -> BuildResult:
    store = InMemoryEventStore()
    ingest(FixtureMailConnector(_CORPUS), store, pipeline_ver="0.1.0-test")
    return build_memory(store)


# --------------------------------------------------------------------- commitments
def test_commitments_panel_groups_by_status_and_direction() -> None:
    mem = _memory()
    panel = commitments_panel(mem, now=_NOW, risk_days=3)

    # Dated overdue → incumplidos; dated within window → en_riesgo; undated → vigentes.
    incumplidos = panel["incumplidos"]
    en_riesgo = panel["en_riesgo"]
    vigentes = panel["vigentes"]

    # Cada grupo tiene las tres direcciones.
    for group in (incumplidos, en_riesgo, vigentes):
        assert set(group.keys()) == {"owed_by_me", "owed_to_me", "unknown"}

    all_incumplidos = [it for items in incumplidos.values() for it in items]
    all_en_riesgo = [it for items in en_riesgo.values() for it in items]
    all_vigentes = [it for items in vigentes.values() for it in items]

    assert all_incumplidos, "el corpus tiene compromisos vencidos"
    assert all_en_riesgo, "el corpus tiene compromisos en riesgo (07/07, 08/07)"
    assert all_vigentes, "el corpus tiene compromisos sin fecha (vigentes)"

    # Invariantes de clasificación.
    today = _NOW.date()
    for it in all_incumplidos:
        assert it["due"] is not None and date.fromisoformat(it["due"]) < today
        assert it["evidence_event"] > 0  # trazabilidad (principio 2)
    for it in all_en_riesgo:
        d = date.fromisoformat(it["due"])
        assert today <= d <= date(2026, 7, 9)
    for it in all_vigentes:
        # Vigentes: sin fecha, o con fecha futura fuera de la ventana de riesgo.
        assert it["due"] is None or date.fromisoformat(it["due"]) > date(2026, 7, 9)

    # Counts coherentes con el contenido.
    counts = panel["counts"]
    assert counts["incumplidos"]["total"] == len(all_incumplidos)
    assert counts["en_riesgo"]["total"] == len(all_en_riesgo)
    assert counts["vigentes"]["total"] == len(all_vigentes)
    assert counts["total"] == len(all_incumplidos) + len(all_en_riesgo) + len(all_vigentes)


def test_commitments_panel_respects_direction_buckets() -> None:
    """Un compromiso con dirección explícita cae en su bucket de dirección."""
    mem = _memory()
    # Inyecta dos compromisos con dirección conocida (uno vencido owed_by_me,
    # uno en riesgo owed_to_me) directamente en el grafo derivado.
    mem.graph.upsert_entity(
        COMMITMENT_KIND, "k-mine",
        attrs={"what": "enviar informe", "due": "2026-06-01",
               "direction": "owed_by_me", "confidence": 0.9},
        first_seen_event=1,
    )
    mem.graph.upsert_entity(
        COMMITMENT_KIND, "k-theirs",
        attrs={"what": "recibir pago", "due": "2026-07-07",
               "direction": "owed_to_me", "confidence": 0.9},
        first_seen_event=2,
    )
    panel = commitments_panel(mem, now=_NOW, risk_days=3)

    mine = [it["what"] for it in panel["incumplidos"]["owed_by_me"]]
    theirs = [it["what"] for it in panel["en_riesgo"]["owed_to_me"]]
    assert "enviar informe" in mine
    assert "recibir pago" in theirs


# ------------------------------------------------------------------------- agents
def test_agents_panel_reflects_stage_and_gates() -> None:
    spec = mail_responder_spec()  # DESIGN, sin approved_at
    approved = spec.model_copy(update={"approved_at": _NOW})

    panel = agents_panel(
        [spec, approved],
        metrics={spec.name: PromotionMetrics(agreement_rate=0.9, coverage_rate=0.8)},
    )
    assert panel["count"] == 2
    row_unapproved, row_approved = panel["agents"]

    # Ambos en DESIGN → siguiente etapa es simulación.
    assert row_unapproved["stage"] == Stage.DESIGN.value
    assert row_unapproved["promotion"]["to_stage"] == Stage.SIMULATION.value
    # Sin aprobación humana del diseño, la compuerta objetiva NO pasa.
    assert row_unapproved["promotion"]["gates_passed"] is False
    # Con approved_at, la compuerta design→simulation pasa.
    assert row_approved["promotion"]["gates_passed"] is True
    # La promoción SIEMPRE requiere humano (§10).
    assert row_approved["promotion"]["requires_human_approval"] is True

    # Métricas reflejadas (las inyectadas para el primero).
    metrics = row_unapproved["metrics"]
    assert metrics["agreement"] == 0.9
    assert metrics["coverage"] == 0.8
    assert set(metrics.keys()) == {"agreement", "coverage", "dangerous_rate", "cost_per_case"}


def test_agents_panel_defaults_metrics_when_absent() -> None:
    spec = mail_responder_spec()
    panel = agents_panel([spec])  # sin métricas
    m = panel["agents"][0]["metrics"]
    # PromotionMetrics por defecto: conservador (dangerous_rate 1.0).
    assert m["dangerous_rate"] == 1.0
    assert m["agreement"] == 0.0


# ------------------------------------------------------------------------ economy
def test_economy_panel_ratio_guarded_against_zero() -> None:
    zero = economy_panel()
    assert zero == {"cost_usd": 0.0, "savings_estimate_usd": 0.0, "net": 0.0, "ratio": None}

    p = economy_panel(llm_cost_usd=10.0, savings_estimate_usd=25.0)
    assert p["net"] == 15.0
    assert p["ratio"] == 2.5


# ---------------------------------------------------------------------- operative
def test_operative_map_counts_entities_and_relations() -> None:
    mem = _memory()
    panel = operative_map_panel(mem)
    as_is = panel["as_is"]

    assert panel["to_be"] == {}
    assert as_is["entity_total"] == len(mem.graph.entities_all())
    assert as_is["relation_total"] == len(mem.graph.all_relations())
    assert sum(as_is["entities_by_kind"].values()) == as_is["entity_total"]
    assert sum(as_is["relations_by_rel"].values()) == as_is["relation_total"]
    # El corpus produce personas, orgs, compromisos y relaciones committed/emailed.
    assert as_is["entities_by_kind"].get(COMMITMENT_KIND, 0) > 0
    assert "committed" in as_is["relations_by_rel"]


# -------------------------------------------------------------------------- inbox
def test_build_decision_inbox_yields_commitment_alerts_with_evidence() -> None:
    mem = _memory()
    inbox = build_decision_inbox(mem, now=_NOW, pipeline_ver="0.1.0-test")
    cards = inbox.pending()

    assert cards, "debería haber alertas de compromiso (vencidos y en riesgo)"
    assert all(c.kind is CardKind.COMMITMENT_ALERT for c in cards)
    # Cada alerta trae evidencia (el evento que la respalda).
    for c in cards:
        assert c.evidence_events and all(e > 0 for e in c.evidence_events)
        assert c.recommendation and "Seguir el compromiso" in c.recommendation

    # Los vencidos tienen mayor urgencia que los en riesgo, y encabezan la cola.
    urgencies = [c.urgency for c in cards]
    assert max(urgencies) == 90  # overdue
    assert 60 in urgencies       # at-risk
    assert urgencies == sorted(urgencies, reverse=True)  # cola por urgencia (§11.2)


def test_card_to_api_shape_for_commitment_and_disambiguation() -> None:
    mem = _memory()
    inbox = build_decision_inbox(mem, now=_NOW)
    commitment_card = inbox.pending()[0]

    api = card_to_api(commitment_card)
    assert set(api.keys()) == {
        "id", "kind", "title", "recommendation", "why",
        "evidence_events", "urgency", "anti_inertia",
    }
    assert api["id"] == str(commitment_card.id)
    assert api["kind"] == "commitment_alert"
    assert isinstance(api["recommendation"], str) and api["recommendation"]
    assert api["why"] == commitment_card.reasoning
    assert api["evidence_events"] == commitment_card.evidence_events

    # Una tarjeta sin recomendación (desambiguación) → recommendation "" (contrato web).
    dis = inbox.add_card(
        kind=CardKind.DISAMBIGUATION,
        title="¿A quién se refiere 'Ana'?",
        recommendation=None,
        reasoning="Dos candidatos, ninguno confiable.",
        created_at=_NOW,
    )
    dis_api = card_to_api(dis)
    assert dis_api["kind"] == "disambiguation"
    assert dis_api["recommendation"] == ""
