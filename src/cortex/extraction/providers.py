"""Proveedor de inferencia API-agnóstico (endpoint compatible con OpenAI).

Este módulo implementa el `InferenceClient` real detrás del seam de `inference.py`.
Es **agnóstico del proveedor**: habla el protocolo `/chat/completions` de OpenAI, que
hoy exponen —entre otros— NVIDIA NIM (`https://integrate.api.nvidia.com/v1`), Ollama
local (`http://127.0.0.1:11434/v1`), vLLM y OpenAI mismo. Cambiar de proveedor es
cambiar `base_url` + `model` en configuración; **ni una línea de código**.

Reglas que respeta (SYSTEM_PROMPT):
- Principio 9 (nada hardcodeado): `base_url`, `api_key` y `model` vienen SIEMPRE de
  configuración/entorno. Este archivo no contiene ninguna URL, key ni model id.
- Regla de costo: sin proveedor configurado no hay cliente real. `build_inference_client()`
  devuelve `UnconfiguredInferenceClient` (que se niega a correr) hasta que el fundador
  inyecte credenciales por entorno. Las credenciales llegan DESDE AFUERA, jamás del repo.
- Principio 3 (contenido observado ≠ instrucciones): el JSON que devuelve el modelo es
  DATO no confiable; lo valida Pydantic aguas arriba (`LLMExtractor`), acá sólo se
  garantiza que la respuesta sea un objeto JSON.

Sin dependencias nuevas: el transporte HTTP por defecto usa la stdlib (`urllib`), detrás
de un `Protocol` inyectable que en tests se reemplaza por un doble (cero red, costo $0).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Protocol

from cortex.extraction.inference import (
    InferenceClient,
    ProviderNotConfigured,
    UnconfiguredInferenceClient,
)
from cortex.settings import Settings, get_settings


class InferenceTransportError(RuntimeError):
    """Fallo de transporte/red o respuesta no parseable del proveedor."""


class HttpTransport(Protocol):
    """Contrato mínimo de transporte HTTP POST→JSON (inyectable para tests)."""

    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]: ...


class UrllibTransport:
    """Transporte HTTP por defecto sobre la stdlib (sin dependencias nuevas)."""

    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # respuesta con status de error
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise InferenceTransportError(
                f"El proveedor respondió {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:  # red/DNS/timeout
            raise InferenceTransportError(f"No se pudo contactar al proveedor: {exc.reason}") from exc
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InferenceTransportError("La respuesta del proveedor no es JSON válido") from exc
        if not isinstance(parsed, dict):
            raise InferenceTransportError("La respuesta del proveedor no es un objeto JSON")
        return parsed


class OpenAICompatibleInferenceClient:
    """Cliente de inferencia contra cualquier endpoint compatible con OpenAI.

    Fuerza salida JSON (`response_format=json_object`) y temperatura 0 para que la
    extracción sea determinista y validable. El `base_url`, la `api_key` y el `model`
    se reciben por parámetro (nunca se leen del entorno acá; eso lo hace la fábrica).
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        transport: HttpTransport | None = None,
        timeout: float = 60.0,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        if not base_url:
            raise ProviderNotConfigured("Falta base_url del proveedor de inferencia.")
        if not model:
            raise ProviderNotConfigured("Falta el model id del proveedor de inferencia.")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._transport: HttpTransport = transport or UrllibTransport()
        self._timeout = timeout
        # `max_tokens` acota el largo (y la latencia). `extra_body` inyecta campos
        # del proveedor (p.ej. desactivar el "thinking" de un modelo de razonamiento
        # para tareas de extracción JSON, que serían lentas si razonan de más).
        # Ambos vienen de configuración: el código sigue siendo API-agnóstico.
        self._max_tokens = max_tokens
        self._extra_body = dict(extra_body) if extra_body else {}

    def complete_json(self, *, system: str, user: str, purpose: str) -> dict[str, Any]:
        url = f"{self._base_url}/chat/completions"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        if self._max_tokens:
            body["max_tokens"] = self._max_tokens
        if self._extra_body:
            body.update(self._extra_body)
        response = self._transport.post_json(
            url, headers=headers, body=body, timeout=self._timeout
        )
        content = _extract_message_content(response)
        try:
            data: Any = json.loads(content)
        except json.JSONDecodeError as exc:
            raise InferenceTransportError(
                f"El modelo no devolvió JSON parseable para purpose={purpose!r}"
            ) from exc
        if not isinstance(data, dict):
            raise InferenceTransportError(
                f"El modelo devolvió un JSON no-objeto para purpose={purpose!r}"
            )
        return data


def _extract_message_content(response: dict[str, Any]) -> str:
    """Extrae `choices[0].message.content` de una respuesta OpenAI-compatible."""
    try:
        choices = response["choices"]
        message = choices[0]["message"]
        content = message["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise InferenceTransportError(
            "Respuesta del proveedor sin choices[0].message.content"
        ) from exc
    if not isinstance(content, str):
        raise InferenceTransportError("El contenido del mensaje no es texto")
    return content


def build_inference_client(
    settings: Settings | None = None,
    *,
    role: str = "fast",
    transport: HttpTransport | None = None,
) -> InferenceClient:
    """Fábrica del cliente de inferencia según configuración (seam de costo).

    `role` elige el ruteo por costo del SYSTEM_PROMPT §5:
    - "fast": extracción masiva / clasificación (settings.fast_model)
    - "core": núcleo cognitivo / juez del simulador (settings.core_model)

    Sin `inference_base_url` y sin el model del rol pedido, devuelve
    `UnconfiguredInferenceClient` (se niega a correr): en dev/CI, costo $0. Las
    credenciales las inyecta el fundador por entorno, nunca vienen del repo.
    """
    cfg = settings if settings is not None else get_settings()
    model = cfg.core_model if role == "core" else cfg.fast_model
    if not cfg.inference_base_url or not model:
        return UnconfiguredInferenceClient()
    extra_body: dict[str, Any] | None = None
    if cfg.inference_extra_body:
        try:
            parsed = json.loads(cfg.inference_extra_body)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            extra_body = parsed
    return OpenAICompatibleInferenceClient(
        base_url=cfg.inference_base_url,
        model=model,
        api_key=cfg.inference_api_key,
        transport=transport,
        max_tokens=cfg.inference_max_tokens or None,
        extra_body=extra_body,
    )
