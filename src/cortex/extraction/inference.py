"""Seam de inferencia — el ÚNICO punto por donde pasaría una llamada a modelo.

Regla de costo (directiva del ecosistema): en dev/CI NO se dispara inferencia
paga. Por eso:

- El cliente por defecto es `UnconfiguredInferenceClient`, que se niega a
  ejecutar: sin proveedor elegido y credenciales explícitas, no hay llamada.
- Los tests inyectan `StaticInferenceClient` (respuestas fijas, costo $0).
- El proveedor real (Anthropic por sección 5, o el stack local gratis —
  Ollama/NIM — que prefiere el ecosistema) es una DECISIÓN DEL FUNDADOR, aún
  pendiente: ver docs/decisions/0003-proveedor-inferencia.md. Ningún camino de
  este módulo llama a un proveedor real todavía.
"""

from __future__ import annotations

from typing import Any, Protocol


class ProviderNotConfigured(RuntimeError):
    """Se intentó inferir sin proveedor configurado (guarda la regla de costo)."""


class InferenceClient(Protocol):
    """Contrato mínimo de inferencia estructurada (JSON adentro, dict afuera)."""

    def complete_json(self, *, system: str, user: str, purpose: str) -> dict[str, Any]: ...


class UnconfiguredInferenceClient:
    """Cliente por defecto: rechaza toda inferencia. Blinda el costo en dev/CI."""

    def complete_json(self, *, system: str, user: str, purpose: str) -> dict[str, Any]:
        raise ProviderNotConfigured(
            "No hay proveedor de inferencia configurado. La elección (Anthropic vs "
            "stack local gratis) es una decisión del fundador pendiente "
            "(docs/decisions/0003-proveedor-inferencia.md). En dev/CI usá "
            "DeterministicExtractor (costo $0) o inyectá StaticInferenceClient."
        )


class StaticInferenceClient:
    """Cliente de pruebas: devuelve payloads fijos por `purpose`. Costo $0.

    Permite ejercitar el camino LLM de punta a punta (prompt→JSON→Pydantic) sin
    tocar ningún proveedor real ni gastar un centavo.
    """

    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self._responses = responses

    def complete_json(self, *, system: str, user: str, purpose: str) -> dict[str, Any]:
        if purpose not in self._responses:
            raise ProviderNotConfigured(
                f"StaticInferenceClient sin respuesta preparada para purpose={purpose!r}"
            )
        return self._responses[purpose]
