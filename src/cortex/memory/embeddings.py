"""Interfaz de embeddings (SYSTEM_PROMPT §5) — F2.

Un `Embedder` convierte texto en un vector de dimensión fija. Se registra
`model`+dimensión en cada chunk (§6) para poder reconstruir/regenerar.

Mismo patrón que el seam de inferencia (regla de costo):
- Por defecto, dev/CI usan `HashingEmbedder`: determinista, local, **costo $0**.
  No es semántico profundo (es un baseline léxico por *feature hashing*), pero
  hace funcionar el retrieval de punta a punta sin proveedor y sin gastar. Sirve
  de default reproducible; el embedder real se enchufa por configuración.
- El embedder real (`OpenAICompatibleEmbedder`) habla el endpoint `/embeddings`
  de OpenAI (NVIDIA NIM, Ollama, ...). `base_url`/`api_key`/`model` viven en
  configuración, jamás en el código (principio 9). Transporte HTTP inyectable →
  testeable sin red.

Sin dependencias nuevas: la aritmética de vectores es stdlib (pequeña escala en
memoria para F2; Postgres+pgvector escala en su momento).
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Protocol

from cortex.extraction.providers import HttpTransport, InferenceTransportError, UrllibTransport
from cortex.settings import Settings, get_settings

_TOKEN_RE = re.compile(r"[0-9a-záéíóúñü]+", re.IGNORECASE)


def l2_normalize(vec: list[float]) -> list[float]:
    """Normaliza a norma 1 (vector cero queda cero)."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    """Similitud coseno. Asume misma dimensión (la valida quien construye el índice)."""
    if len(a) != len(b):
        raise ValueError(f"dimensiones distintas: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class Embedder(Protocol):
    """Contrato de embeddings: texto → vector de dimensión fija."""

    @property
    def model(self) -> str: ...
    @property
    def dim(self) -> int: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class UnconfiguredEmbedder:
    """Embedder que se niega a correr. Guarda la regla de costo si se elige
    explícitamente 'sin embeddings' (no es el default: el default es el Hashing)."""

    @property
    def model(self) -> str:
        return "unconfigured"

    @property
    def dim(self) -> int:
        return 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise InferenceTransportError(
            "No hay embedder configurado. Usá HashingEmbedder (costo $0) o configurá "
            "CORTEX_INFERENCE_BASE_URL + CORTEX_EMBED_MODEL para un proveedor real."
        )


class HashingEmbedder:
    """Embedder determinista local (feature hashing con signo), costo $0.

    Cada token (y bigrama) se mapea a un bucket de `dim` por hash estable
    (blake2b) con un signo también derivado del hash — el *hashing trick* clásico.
    El vector se L2-normaliza. Resultado: reproducible entre corridas y máquinas,
    con similitud coseno que refleja solapamiento léxico. Baseline honesto para
    F2; el salto a embeddings semánticos reales es cambiar config, no código.
    """

    def __init__(self, dim: int = 1024) -> None:
        if dim <= 0:
            raise ValueError("dim debe ser > 0")
        self._dim = dim

    @property
    def model(self) -> str:
        return f"hashing-v1-{self._dim}"

    @property
    def dim(self) -> int:
        return self._dim

    def _bucket_and_sign(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        bucket = value % self._dim
        sign = 1.0 if (value >> 63) & 1 else -1.0
        return bucket, sign

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        toks = _tokens(text)
        features: list[str] = list(toks)
        features.extend(f"{a}_{b}" for a, b in zip(toks, toks[1:]))  # bigramas
        for feat in features:
            bucket, sign = self._bucket_and_sign(feat)
            vec[bucket] += sign
        return l2_normalize(vec)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class OpenAICompatibleEmbedder:
    """Embedder contra un endpoint `/embeddings` compatible con OpenAI.

    NVIDIA NIM / Ollama / OpenAI: cambia `base_url`+`model` por configuración.
    Nada hardcodeado. Transporte inyectable (tests sin red).
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dim: int,
        api_key: str = "",
        transport: HttpTransport | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not base_url:
            raise InferenceTransportError("Falta base_url del proveedor de embeddings.")
        if not model:
            raise InferenceTransportError("Falta el model id de embeddings.")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dim = dim
        self._api_key = api_key
        self._transport: HttpTransport = transport or UrllibTransport()
        self._timeout = timeout

    @property
    def model(self) -> str:
        return self._model

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self._base_url}/embeddings"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body: dict[str, Any] = {"model": self._model, "input": texts}
        response = self._transport.post_json(
            url, headers=headers, body=body, timeout=self._timeout
        )
        return self._parse(response, expected=len(texts))

    def _parse(self, response: dict[str, Any], *, expected: int) -> list[list[float]]:
        data = response.get("data")
        if not isinstance(data, list) or len(data) != expected:
            raise InferenceTransportError("Respuesta de embeddings sin 'data' del tamaño esperado")
        out: list[list[float]] = []
        for item in data:
            emb = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(emb, list) or not all(isinstance(x, (int, float)) for x in emb):
                raise InferenceTransportError("Un embedding de la respuesta no es una lista numérica")
            if len(emb) != self._dim:
                raise InferenceTransportError(
                    f"Dimensión de embedding inesperada: {len(emb)} != {self._dim}"
                )
            out.append([float(x) for x in emb])
        return out


def build_embedder(
    settings: Settings | None = None,
    *,
    transport: HttpTransport | None = None,
) -> Embedder:
    """Fábrica del embedder según configuración.

    Con `CORTEX_INFERENCE_BASE_URL` + `CORTEX_EMBED_MODEL` configurados, usa el
    proveedor real (OpenAI-compatible). Si no, cae al `HashingEmbedder` ($0):
    el retrieval funciona igual, de forma determinista, sin gastar un centavo.
    """
    cfg = settings if settings is not None else get_settings()
    if cfg.inference_base_url and cfg.embed_model:
        return OpenAICompatibleEmbedder(
            base_url=cfg.inference_base_url,
            model=cfg.embed_model,
            dim=cfg.embedding_dim,
            api_key=cfg.inference_api_key,
            transport=transport,
        )
    return HashingEmbedder(dim=cfg.embedding_dim)
