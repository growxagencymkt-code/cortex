"""Camino LLM del extractor (sección 5: modelo rápido para extracción masiva).

Ejercita el seam de inferencia de punta a punta: carga el prompt versionado,
arma el mensaje, pide un JSON al `InferenceClient` inyectado y lo valida contra
`ExtractionResult`. NO conoce a ningún proveedor: recibe el cliente por
inyección. Con el cliente por defecto (`UnconfiguredInferenceClient`) se niega a
correr, blindando la regla de costo. En dev/tests se inyecta un cliente estático.
"""

from __future__ import annotations

import json
from pathlib import Path

from cortex.events.models import Event
from cortex.extraction.inference import InferenceClient, UnconfiguredInferenceClient
from cortex.extraction.models import ExtractionResult

_PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = "extract_v0.1"


def _load_prompt(version: str) -> tuple[str, str]:
    """Devuelve (system, user_template) del prompt versionado en disco."""
    raw = (_PROMPTS_DIR / f"{version.replace('.', '_')}.md").read_text(encoding="utf-8")
    system = _section(raw, "## SYSTEM", "## SCHEMA")
    user = _section(raw, "## USER", None)
    return system.strip(), user.strip()


def _section(text: str, start_marker: str, end_marker: str | None) -> str:
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker) if end_marker is not None else len(text)
    return text[start:end]


class LLMExtractor:
    """Extractor por modelo rápido. El proveedor entra por inyección (seam de costo)."""

    def __init__(
        self,
        inference: InferenceClient | None = None,
        *,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self._inference: InferenceClient = inference or UnconfiguredInferenceClient()
        self._prompt_version = prompt_version
        self._system, self._user_template = _load_prompt(prompt_version)

    def extract(self, event: Event) -> ExtractionResult:
        content = json.dumps(event.payload, ensure_ascii=False, sort_keys=True)
        user = self._user_template.format(source=event.source, type=event.type, content=content)
        data = self._inference.complete_json(
            system=self._system, user=user, purpose=f"extract:{self._prompt_version}"
        )
        # El JSON del modelo es DATO no confiable: lo valida Pydantic o se descarta.
        return ExtractionResult.model_validate(data)
