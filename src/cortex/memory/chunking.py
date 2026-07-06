"""Chunking del contenido de un evento (SYSTEM_PROMPT §7, paso 6) — F2.

Parte el texto de un evento en fragmentos de ~300–500 tokens con solapamiento,
para indexarlos con embeddings. Los tokens se aproximan por palabras (whitespace):
suficiente y determinista para F2; el conteo exacto por tokenizador del modelo se
puede afinar cuando el embedder real lo requiera.

Principio 3: el contenido es DATO. Este módulo sólo lo trocea; no lo interpreta
ni ejecuta nada de lo que lea.
"""

from __future__ import annotations

from cortex.events.models import Event

# Campos de payload que aportan texto legible, en orden de relevancia.
_TEXT_FIELDS = ("subject", "title", "body", "text", "content", "summary", "transcript")


def event_text(event: Event) -> str:
    """Extrae el texto legible del evento a partir de su payload.

    Usa campos conocidos (subject/body/...) si existen; si no, concatena los
    valores string del payload. Determinista y sin efectos.
    """
    payload = event.payload
    parts: list[str] = []
    used: set[str] = set()
    for field in _TEXT_FIELDS:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
            used.add(field)
    if not parts:
        for key, value in payload.items():
            if key not in used and isinstance(value, str) and value.strip():
                parts.append(value.strip())
    return "\n".join(parts)


def chunk_text(
    text: str,
    *,
    target_tokens: int = 400,
    overlap_tokens: int = 60,
) -> list[str]:
    """Trocea `text` en fragmentos de ~`target_tokens` palabras con solapamiento.

    - `target_tokens` en [1, ∞): tamaño objetivo por chunk (aprox. palabras).
    - `overlap_tokens` en [0, target_tokens): palabras compartidas entre chunks
      consecutivos, para no cortar contexto en el borde.
    Devuelve [] si el texto está vacío. Un texto corto da un único chunk.
    """
    if target_tokens < 1:
        raise ValueError("target_tokens debe ser >= 1")
    if not (0 <= overlap_tokens < target_tokens):
        raise ValueError("overlap_tokens debe estar en [0, target_tokens)")

    words = text.split()
    if not words:
        return []
    step = target_tokens - overlap_tokens
    chunks: list[str] = []
    start = 0
    while start < len(words):
        window = words[start : start + target_tokens]
        chunks.append(" ".join(window))
        if start + target_tokens >= len(words):
            break
        start += step
    return chunks


def chunks_for_event(event: Event, *, target_tokens: int = 400, overlap_tokens: int = 60) -> list[str]:
    """Texto del evento troceado listo para embeddings."""
    return chunk_text(event_text(event), target_tokens=target_tokens, overlap_tokens=overlap_tokens)
