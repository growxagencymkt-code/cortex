"""Tests del seam de embeddings (F2). Cero red, costo $0."""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from cortex.memory.embeddings import (
    HashingEmbedder,
    OpenAICompatibleEmbedder,
    build_embedder,
    cosine,
    l2_normalize,
)
from cortex.settings import Settings


def test_hashing_embedder_is_deterministic_and_normalized() -> None:
    emb = HashingEmbedder(dim=256)
    a1 = emb.embed(["reunión con Ana sobre el presupuesto"])[0]
    a2 = emb.embed(["reunión con Ana sobre el presupuesto"])[0]
    assert a1 == a2  # determinista
    assert len(a1) == 256
    assert math.isclose(math.sqrt(sum(x * x for x in a1)), 1.0, rel_tol=1e-9)


def test_hashing_embedder_similarity_reflects_lexical_overlap() -> None:
    emb = HashingEmbedder(dim=1024)
    base, near, far = emb.embed(
        [
            "el presupuesto de marketing para el segundo trimestre",
            "presupuesto de marketing del segundo trimestre revisado",
            "el gato duerme en el tejado bajo la lluvia",
        ]
    )
    assert cosine(base, near) > cosine(base, far)


def test_l2_normalize_zero_vector_is_safe() -> None:
    assert l2_normalize([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]


def test_cosine_dimension_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        cosine([1.0, 0.0], [1.0, 0.0, 0.0])


class _FakeEmbTransport:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self, url: str, *, headers: dict[str, str], body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "headers": headers, "body": body})
        inputs = body["input"]
        return {"data": [{"embedding": [0.1] * self.dim} for _ in inputs]}


def test_openai_compatible_embedder_request_and_parse() -> None:
    tr = _FakeEmbTransport(dim=8)
    emb = OpenAICompatibleEmbedder(
        base_url="https://integrate.api.nvidia.com/v1",
        model="nvidia/nv-embed-v1",
        dim=8,
        api_key="nvapi-x",
        transport=tr,
    )
    out = emb.embed(["hola", "chau"])
    assert len(out) == 2 and all(len(v) == 8 for v in out)
    call = tr.calls[0]
    assert call["url"] == "https://integrate.api.nvidia.com/v1/embeddings"
    assert call["headers"]["Authorization"] == "Bearer nvapi-x"
    assert call["body"]["model"] == "nvidia/nv-embed-v1"
    assert json.dumps(call["body"]["input"]) == json.dumps(["hola", "chau"])


def test_openai_embedder_empty_input_returns_empty_without_call() -> None:
    tr = _FakeEmbTransport(dim=4)
    emb = OpenAICompatibleEmbedder(base_url="http://x/v1", model="m", dim=4, transport=tr)
    assert emb.embed([]) == []
    assert tr.calls == []


def test_factory_defaults_to_hashing_when_unconfigured() -> None:
    e = build_embedder(Settings(inference_base_url="", embed_model="", embedding_dim=512))
    assert isinstance(e, HashingEmbedder)
    assert e.dim == 512


def test_factory_builds_real_embedder_when_configured() -> None:
    e = build_embedder(
        Settings(
            inference_base_url="https://integrate.api.nvidia.com/v1",
            embed_model="nvidia/nv-embed-v1",
            embedding_dim=1024,
        ),
        transport=_FakeEmbTransport(dim=1024),
    )
    assert isinstance(e, OpenAICompatibleEmbedder)
    assert e.model == "nvidia/nv-embed-v1"
