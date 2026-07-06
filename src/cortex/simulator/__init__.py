"""Simulador: mide agentes contra el pasado real; jamás toca el mundo real — F3.

API pública (SYSTEM_PROMPT §9):
- `simulate(spec, t0, t1, *, store, ground_truth, judge=None, ...) -> SimulationReport`
- Snapshot temporal: `build_snapshot`, `MemorySnapshot`, `TimeFilteredEventStore`.
- Sandbox de herramientas: `Sandbox`, `ProposedAction`.
- Agente bajo prueba: `AgentPolicy`, `AgentContext`, `AgentDecision`,
  `reference_mail_drafter`, `escalate_all_policy`.
- Evaluador 3 niveles: `evaluate_hard_rules` (N1), `Judge`/`StructuralJudge`/
  `LLMJudge` (N2), `sample_for_human_review`/`calibrate_against_humans` (N3),
  `Verdict`, `GroundTruth`.
- Reporte y compuertas: `SimulationReport`, `SimulationCaseResult`,
  `InjectionCaseResult`.
- Corpus de inyección: `load_injection_corpus`.
"""

from __future__ import annotations

from cortex.simulator.agent import (
    AgentContext,
    AgentDecision,
    AgentPolicy,
    escalate_all_policy,
    reference_mail_drafter,
)
from cortex.simulator.evaluation import (
    AGREEMENT_VERDICTS,
    DIVERGENCE_THRESHOLD,
    EXFIL_MARKERS,
    GroundTruth,
    HumanCalibration,
    HardViolation,
    Judge,
    JudgeResult,
    LLMJudge,
    StructuralJudge,
    Verdict,
    calibrate_against_humans,
    evaluate_hard_rules,
    judge_prompt_v1,
    sample_for_human_review,
)
from cortex.simulator.injection import default_corpus_path, load_injection_corpus
from cortex.simulator.report import (
    InjectionCaseResult,
    SimulationCaseResult,
    SimulationReport,
    build_report,
)
from cortex.simulator.run import simulate
from cortex.simulator.sandbox import ProposedAction, Sandbox, extract_emails
from cortex.simulator.snapshot import MemorySnapshot, build_snapshot
from cortex.simulator.store import SimulatorWriteAttempt, TimeFilteredEventStore

__all__ = [
    # contrato principal
    "simulate",
    "SimulationReport",
    "SimulationCaseResult",
    "InjectionCaseResult",
    "build_report",
    # snapshot temporal
    "build_snapshot",
    "MemorySnapshot",
    "TimeFilteredEventStore",
    "SimulatorWriteAttempt",
    # sandbox
    "Sandbox",
    "ProposedAction",
    "extract_emails",
    # agente bajo prueba
    "AgentPolicy",
    "AgentContext",
    "AgentDecision",
    "reference_mail_drafter",
    "escalate_all_policy",
    # evaluador
    "evaluate_hard_rules",
    "HardViolation",
    "Judge",
    "JudgeResult",
    "StructuralJudge",
    "LLMJudge",
    "judge_prompt_v1",
    "Verdict",
    "GroundTruth",
    "AGREEMENT_VERDICTS",
    "EXFIL_MARKERS",
    "sample_for_human_review",
    "calibrate_against_humans",
    "HumanCalibration",
    "DIVERGENCE_THRESHOLD",
    # corpus de inyección
    "load_injection_corpus",
    "default_corpus_path",
]
