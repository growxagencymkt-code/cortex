"""Extracción estructurada (modelo rápido, JSON validado con Pydantic) — F1.

API pública:
- Contratos: ExtractionResult y sus partes (extraction.models).
- Extractor por defecto (costo $0, sin modelo): DeterministicExtractor.
- Camino LLM detrás del seam de inferencia (sin proveedor real): LLMExtractor.
"""

from __future__ import annotations

from cortex.extraction.extractor import DeterministicExtractor, Extractor
from cortex.extraction.inference import (
    InferenceClient,
    ProviderNotConfigured,
    StaticInferenceClient,
    UnconfiguredInferenceClient,
)
from cortex.extraction.llm_extractor import LLMExtractor
from cortex.extraction.models import (
    ExtractedCommitment,
    ExtractedDecision,
    ExtractedEntity,
    ExtractedOpenQuestion,
    ExtractedRelation,
    ExtractionResult,
)

__all__ = [
    "DeterministicExtractor",
    "Extractor",
    "ExtractionResult",
    "ExtractedEntity",
    "ExtractedRelation",
    "ExtractedCommitment",
    "ExtractedDecision",
    "ExtractedOpenQuestion",
    "InferenceClient",
    "StaticInferenceClient",
    "UnconfiguredInferenceClient",
    "ProviderNotConfigured",
    "LLMExtractor",
]
