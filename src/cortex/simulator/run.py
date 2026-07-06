"""Contrato del simulador: `simulate(...)` (SYSTEM_PROMPT §9.1).

Reproduce en orden los eventos disparadores del agente en la ventana [t0, t1] y,
por cada uno, mide la conducta del agente contra la realidad pasada. JAMÁS ejecuta
efectos reales: toda escritura pasa por el sandbox (§9.2).

Flujo por caso de negocio:
  1. Snapshot temporal a `t = evento.ts` (sólo events.ts <= t; sin fuga temporal).
  2. Sandbox de herramientas sobre ese snapshot (lecturas reales, escrituras
     registradas).
  3. La política del agente decide (misma spec que en prod; sólo cambia la tool
     injection).
  4. N1 reglas duras sobre las acciones propuestas → si hay violación, `dangerous`.
  5. N2 juez (por defecto determinista $0; opcional LLM detrás del seam) vs el
     ground truth humano del caso.

Además, en TODA corrida (§9.4) se pasa el corpus de inyección por el MISMO agente:
cualquier obediencia = `dangerous` = la corrida falla la compuerta.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from cortex.agents.specs import AgentSpec
from cortex.events.models import Event
from cortex.events.store import EventStore
from cortex.extraction.extractor import Extractor
from cortex.simulator.agent import AgentContext, AgentPolicy, escalate_all_policy
from cortex.simulator.evaluation import (
    GroundTruth,
    Judge,
    StructuralJudge,
    Verdict,
    calibrate_against_humans,
    evaluate_hard_rules,
)
from cortex.simulator.injection import load_injection_corpus
from cortex.simulator.report import (
    InjectionCaseResult,
    SimulationCaseResult,
    SimulationReport,
    build_report,
)
from cortex.simulator.sandbox import Sandbox
from cortex.simulator.snapshot import build_snapshot


def _matches_triggers(event: Event, triggers: list[dict[str, str]]) -> bool:
    """True si el evento activa al agente. Sin triggers declarados → todo activa.

    Cada trigger es un dict de campos del evento (típicamente {source,type}); el
    evento activa si coincide en TODOS los campos declarados de AL MENOS un trigger.
    """
    if not triggers:
        return True
    fields = {"source": event.source, "type": event.type, "actor": event.actor or ""}
    return any(
        all(fields.get(k) == v for k, v in trig.items()) for trig in triggers
    )


def _gt_key(event: Event) -> str:
    """Clave del ground truth para un evento (external_id, o id como fallback)."""
    return event.external_id if event.external_id is not None else str(event.id)


def simulate(
    spec: AgentSpec,
    t0: datetime,
    t1: datetime,
    *,
    store: EventStore,
    ground_truth: Mapping[str, GroundTruth],
    judge: Judge | None = None,
    policy: AgentPolicy | None = None,
    extractor: Extractor | None = None,
    injection_corpus: list[Event] | None = None,
    human_verdicts: Mapping[str, Verdict] | None = None,
) -> SimulationReport:
    """Simula al agente `spec` sobre [t0, t1] contra el histórico. No ejecuta efectos.

    Parámetros del contrato §9.1: `spec`, `t0`, `t1`, `store`, `ground_truth`,
    `judge`. `policy` modela la conducta del agente-bajo-prueba (en F4 será el LLM
    detrás del seam; en F3 se inyecta para simular a $0 y de forma determinista);
    por defecto escala todo (seguro). `judge` por defecto es `StructuralJudge`
    ($0); pasá `LLMJudge(inference)` para el juez LLM detrás del seam.

    `ground_truth`: mapea `external_id` del evento disparador → acción humana real.
    `human_verdicts`: opcional, veredictos humanos por caso para calibración N3.
    """
    active_judge: Judge = judge if judge is not None else StructuralJudge()
    active_policy: AgentPolicy = policy if policy is not None else escalate_all_policy

    # --- Casos de negocio: disparadores en [t0, t1] en orden del log -----------
    case_results: list[SimulationCaseResult] = []
    judge_verdicts: dict[str, Verdict] = {}
    for event in store.all_events():
        if not (t0 <= event.ts <= t1):
            continue
        if not _matches_triggers(event, spec.triggers):
            continue

        result = _run_case(spec, event, store, active_policy, active_judge, ground_truth, extractor)
        case_results.append(result)
        judge_verdicts[result.case_id] = result.verdict

    # --- Suite de inyección: SIEMPRE, por el mismo agente (§9.4) ----------------
    corpus = injection_corpus if injection_corpus is not None else load_injection_corpus()
    injection_results: list[InjectionCaseResult] = [
        _run_injection_case(spec, vector, active_policy, extractor) for vector in corpus
    ]

    # --- N3: calibración humana (stub) -----------------------------------------
    human_calibration = None
    if human_verdicts:
        human_calibration = calibrate_against_humans(judge_verdicts, human_verdicts)

    pv = spec.permissions.get("pipeline_ver")
    pipeline_ver = pv if isinstance(pv, str) else "0.0.0"

    return build_report(
        agent_name=spec.name,
        agent_version=spec.version,
        window_start=t0,
        window_end=t1,
        pipeline_ver=pipeline_ver,
        gate=spec.metrics_gate,
        case_results=case_results,
        injection_results=injection_results,
        human_calibration=human_calibration,
    )


def _run_case(
    spec: AgentSpec,
    event: Event,
    store: EventStore,
    policy: AgentPolicy,
    judge: Judge,
    ground_truth: Mapping[str, GroundTruth],
    extractor: Extractor | None,
) -> SimulationCaseResult:
    """Corre UN caso de negocio: snapshot → sandbox → política → N1 → N2."""
    snapshot = build_snapshot(store, event.ts, extractor=extractor)
    sandbox = Sandbox(snapshot=snapshot, trigger=event)
    decision = policy(AgentContext(spec=spec, trigger=event, sandbox=sandbox))

    violations = evaluate_hard_rules(spec, event, snapshot, sandbox.proposed_actions)

    case_id = _gt_key(event)
    if violations:
        return SimulationCaseResult(
            case_id=case_id,
            trigger_external_id=event.external_id,
            verdict=Verdict.DANGEROUS,
            handled=decision.handled,
            escalated=not decision.handled,
            hard_violations=[f"{v.rule}: {v.detail}" for v in violations],
            cost_usd=0.0,
            rationale="regla dura violada (N1)",
        )

    gt = ground_truth.get(case_id)
    if gt is None:
        # Sin ground truth no se puede juzgar acuerdo: se cuenta como cobertura,
        # veredicto `different` (no penaliza acuerdo ni marca peligro).
        return SimulationCaseResult(
            case_id=case_id,
            trigger_external_id=event.external_id,
            verdict=Verdict.DIFFERENT,
            handled=decision.handled,
            escalated=not decision.handled,
            rationale="sin ground truth para este caso",
        )

    verdict_result = judge.evaluate(
        spec=spec, trigger=event, agent_action=decision.action, ground_truth=gt
    )
    return SimulationCaseResult(
        case_id=case_id,
        trigger_external_id=event.external_id,
        verdict=verdict_result.verdict,
        handled=decision.handled,
        escalated=not decision.handled,
        cost_usd=verdict_result.cost_usd,
        rationale=verdict_result.rationale,
    )


def _run_injection_case(
    spec: AgentSpec,
    vector: Event,
    policy: AgentPolicy,
    extractor: Extractor | None,
) -> InjectionCaseResult:
    """Corre UN vector de inyección por el agente. Obediencia = N1 con dientes.

    El snapshot es vacío (el vector no viene del log real): lo único que importa es
    que el agente NO obedezca la instrucción embebida. Las reglas duras (destino no
    fundamentado / exfiltración / acción irreversible sobre contenido observado)
    detectan cualquier obediencia.
    """
    from cortex.events.store import InMemoryEventStore

    empty_store = InMemoryEventStore()
    snapshot = build_snapshot(empty_store, vector.ts, extractor=extractor)
    sandbox = Sandbox(snapshot=snapshot, trigger=vector)
    policy(AgentContext(spec=spec, trigger=vector, sandbox=sandbox))

    violations = evaluate_hard_rules(spec, vector, snapshot, sandbox.proposed_actions)
    vector_id = vector.external_id or str(vector.id)
    return InjectionCaseResult(
        vector_id=vector_id,
        obeyed=bool(violations),
        violations=[f"{v.rule}: {v.detail}" for v in violations],
    )
