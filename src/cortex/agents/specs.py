"""Contrato de especificación de agentes (SYSTEM_PROMPT §6 + §10) — base F3/F4.

`AgentSpec` es el objeto que viaja por todo el ciclo de vida de un agente
(diseño → simulación → sombra → canario → producción → retirado). Es idéntico
en simulación y en producción: sólo cambia la inyección de herramientas (§9.2).

Espeja la tabla `agent_specs` (§6):
    agent_specs(id UUID, name TEXT, version INT, stage TEXT, prompt TEXT,
                tools JSONB, triggers JSONB, permissions JSONB, metrics_gate JSONB,
                created_by TEXT, approved_at TIMESTAMPTZ, UNIQUE(name,version))

Este módulo es un CONTRATO compartido (lo importan el simulador y el
orquestador). No ejecuta nada: define datos.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class Stage(str, Enum):
    """Etapas del ciclo de vida (§10). El orden es el de promoción."""

    DESIGN = "design"
    SIMULATION = "simulation"
    SHADOW = "shadow"
    CANARY = "canary"
    PRODUCTION = "production"
    RETIRED = "retired"


# Orden de promoción para comparar/validar transiciones (retired queda fuera).
STAGE_ORDER: tuple[Stage, ...] = (
    Stage.DESIGN,
    Stage.SIMULATION,
    Stage.SHADOW,
    Stage.CANARY,
    Stage.PRODUCTION,
)


class ToolSpec(BaseModel):
    """Una herramienta que el agente puede usar. En simulación se reemplaza por
    un doble (§9.2): lecturas sobre el snapshot, escrituras registran acción."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    # Clase de reversibilidad de los efectos de la tool (§4). Se valida contra
    # governance.reversibility.Reversibility en quien la consuma.
    reversibility: str = "reversible"


class MetricsGate(BaseModel):
    """Compuertas métricas para promover de etapa (§9.3, §10).

    - agreement_min: %(equivalent+better) mínimo para pasar simulación.
    - dangerous_rate_max: tasa peligrosa máxima (DEBE ser 0 para promover).
    - coverage_min: %(manejó vs escaló) mínimo.
    - cost_per_case_max_usd: techo de costo por caso (None = sin techo).
    """

    model_config = ConfigDict(frozen=True)

    agreement_min: float = 0.80
    dangerous_rate_max: float = 0.0
    coverage_min: float = 0.0
    cost_per_case_max_usd: float | None = None


class AgentSpec(BaseModel):
    """Especificación versionada de un agente. Inmutable: una modificación es una
    versión nueva (UNIQUE(name,version)), y toda versión nueva es un canario (§6)."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    name: str
    version: int = 1
    stage: Stage = Stage.DESIGN
    prompt: str
    tools: list[ToolSpec] = Field(default_factory=list)
    # Disparadores: qué eventos (source/type) activan al agente.
    triggers: list[dict[str, str]] = Field(default_factory=list)
    # Permisos: acciones/tools autorizadas, destinatarios permitidos, etc.
    permissions: dict[str, object] = Field(default_factory=dict)
    metrics_gate: MetricsGate = Field(default_factory=MetricsGate)
    created_by: str = "founder"
    approved_at: datetime | None = None  # sello humano de la compuerta de diseño

    def is_human_approved(self) -> bool:
        """Diseño aprobado por un humano (compuerta para entrar a simulación)."""
        return self.approved_at is not None
