"""Tests del proveedor de inferencia API-agnóstico (OpenAI-compatible).

Cero red, costo $0: se inyecta un `HttpTransport` doble que captura la request y
devuelve una respuesta fija. Verifica el contrato hacia el proveedor (URL, headers,
body, forzado de JSON) y la fábrica que respeta la regla de costo.

Ningún proveedor real se contacta nunca (principio de costo del ecosistema).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from cortex.extraction import (
    ExtractionResult,
    InferenceTransportError,
    LLMExtractor,
    OpenAICompatibleInferenceClient,
    ProviderNotConfigured,
    UnconfiguredInferenceClient,
    build_inference_client,
)
from cortex.events.models import Event
from cortex.settings import Settings


class _CapturingTransport:
    """Doble de transporte: guarda la última request y devuelve una respuesta fija."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "headers": headers, "body": body, "timeout": timeout})
        return {"choices": [{"message": {"role": "assistant", "content": self._content}}]}


def _event() -> Event:
    from datetime import UTC, datetime

    return Event(
        id=1,
        ts=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        ingested_at=datetime.now(tz=UTC),
        source="gmail",
        type="email.received",
        external_id="prov-1",
        actor="alguien@externo.com",
        payload={"body": "hola", "from": "alguien@externo.com"},
        pipeline_ver="0.1.0-test",
    )


def test_builds_openai_compatible_request() -> None:
    transport = _CapturingTransport(content=json.dumps({"entities": []}))
    client = OpenAICompatibleInferenceClient(
        base_url="https://integrate.api.nvidia.com/v1",
        model="meta/llama-3.1-8b-instruct",
        api_key="nvapi-secret",
        transport=transport,
    )

    out = client.complete_json(system="S", user="U", purpose="extract:test")

    assert out == {"entities": []}
    assert len(transport.calls) == 1
    call = transport.calls[0]
    # URL compone el path /chat/completions sobre el base_url configurado.
    assert call["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    # La API key viaja como Bearer y NO está hardcodeada en el código.
    assert call["headers"]["Authorization"] == "Bearer nvapi-secret"
    body = call["body"]
    assert body["model"] == "meta/llama-3.1-8b-instruct"
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0] == {"role": "system", "content": "S"}
    assert body["messages"][1] == {"role": "user", "content": "U"}


def test_no_authorization_header_without_key() -> None:
    transport = _CapturingTransport(content="{}")
    client = OpenAICompatibleInferenceClient(
        base_url="http://127.0.0.1:11434/v1",  # Ollama: sin key
        model="llama3.1",
        transport=transport,
    )
    client.complete_json(system="S", user="U", purpose="p")
    assert "Authorization" not in transport.calls[0]["headers"]


def test_rejects_missing_base_url_or_model() -> None:
    with pytest.raises(ProviderNotConfigured):
        OpenAICompatibleInferenceClient(base_url="", model="m")
    with pytest.raises(ProviderNotConfigured):
        OpenAICompatibleInferenceClient(base_url="http://x/v1", model="")


def test_non_object_json_from_model_is_rejected() -> None:
    transport = _CapturingTransport(content="[1, 2, 3]")  # JSON válido pero no-objeto
    client = OpenAICompatibleInferenceClient(
        base_url="http://x/v1", model="m", transport=transport
    )
    with pytest.raises(InferenceTransportError):
        client.complete_json(system="S", user="U", purpose="p")


def test_non_json_content_is_rejected() -> None:
    transport = _CapturingTransport(content="no soy json")
    client = OpenAICompatibleInferenceClient(
        base_url="http://x/v1", model="m", transport=transport
    )
    with pytest.raises(InferenceTransportError):
        client.complete_json(system="S", user="U", purpose="p")


def test_malformed_provider_response_is_rejected() -> None:
    class _BadTransport:
        def post_json(
            self, url: str, *, headers: dict[str, str], body: dict[str, Any], timeout: float
        ) -> dict[str, Any]:
            return {"unexpected": "shape"}  # sin choices

    client = OpenAICompatibleInferenceClient(
        base_url="http://x/v1", model="m", transport=_BadTransport()
    )
    with pytest.raises(InferenceTransportError):
        client.complete_json(system="S", user="U", purpose="p")


# --- Fábrica: regla de costo ($0 si no hay proveedor configurado) ------------


def test_factory_unconfigured_without_base_url() -> None:
    settings = Settings(inference_base_url="", fast_model="", core_model="")
    client = build_inference_client(settings, role="fast")
    assert isinstance(client, UnconfiguredInferenceClient)
    with pytest.raises(ProviderNotConfigured):
        client.complete_json(system="S", user="U", purpose="p")


def test_factory_unconfigured_when_role_model_missing() -> None:
    # Hay base_url pero falta el model del rol pedido → no se arma cliente real.
    settings = Settings(
        inference_base_url="https://integrate.api.nvidia.com/v1",
        fast_model="fast-x",
        core_model="",
    )
    assert isinstance(build_inference_client(settings, role="core"), UnconfiguredInferenceClient)


def test_factory_builds_real_client_when_configured() -> None:
    settings = Settings(
        inference_base_url="https://integrate.api.nvidia.com/v1",
        inference_api_key="nvapi-x",
        fast_model="meta/llama-3.1-8b-instruct",
        core_model="meta/llama-3.1-70b-instruct",
    )
    transport = _CapturingTransport(content=json.dumps({"entities": []}))
    fast = build_inference_client(settings, role="fast", transport=transport)
    assert isinstance(fast, OpenAICompatibleInferenceClient)
    fast.complete_json(system="S", user="U", purpose="p")
    assert transport.calls[0]["body"]["model"] == "meta/llama-3.1-8b-instruct"

    core = build_inference_client(settings, role="core", transport=transport)
    assert isinstance(core, OpenAICompatibleInferenceClient)
    core.complete_json(system="S", user="U", purpose="p")
    assert transport.calls[1]["body"]["model"] == "meta/llama-3.1-70b-instruct"


def test_llm_extractor_end_to_end_with_configured_provider() -> None:
    """El camino LLM completo (prompt→proveedor→JSON→Pydantic) sin tocar la red."""
    payload = {
        "entities": [{"kind": "person", "name": "Ana", "mention": "Ana"}],
        "relations": [],
        "commitments": [],
        "decisions": [],
        "open_questions": [],
    }
    transport = _CapturingTransport(content=json.dumps(payload))
    client = OpenAICompatibleInferenceClient(
        base_url="https://integrate.api.nvidia.com/v1",
        model="meta/llama-3.1-8b-instruct",
        api_key="nvapi-x",
        transport=transport,
    )
    result = LLMExtractor(client).extract(_event())
    assert isinstance(result, ExtractionResult)
    assert [e.name for e in result.entities] == ["Ana"]
