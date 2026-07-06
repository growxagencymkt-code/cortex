"""Resolución y desambiguación de entidades (sección 7, paso 4).

Cascada: exacto → alias → embedding (vecino más cercano) → si nada supera el
umbral, pregunta de desambiguación a la bandeja humana (sección 11.2). El
`CONFIDENCE_THRESHOLD` = 0.8 implementa la regla de la sección 6: "entidad nueva
con confidence<0.8 → pregunta de desambiguación en bandeja, no se escribe
directo".

Regla de costo (principio 8): en F1 NO hay embeddings ni proveedor real. El
`Embedder` es un seam opcional para F2; por defecto es None y NUNCA se llama a un
proveedor pago. Los tests usan un embedder falso determinista.

`resolve()` es de SOLO LECTURA: nunca escribe al grafo. Devuelve uno de tres
resultados y el LLAMADOR (el pipeline de ingesta, fuera de este módulo) decide:
- `Resolved`          → hay una entidad existente que corresponde; usala.
- `NeedsDisambiguation`→ hay candidatos pero ninguno es confiable; a la bandeja.
- `Unresolved`        → no hay ningún candidato; el llamador CREA una entidad
                         nueva (resolución no crea porque no escribe).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from cortex.extraction.models import ExtractedEntity
from cortex.memory.graph import EntityRecord, InMemoryGraph

# Umbral de la sección 6: por debajo de esto una entidad nueva no se escribe
# directo, va a desambiguación.
CONFIDENCE_THRESHOLD = 0.8

# Confianza asignada a un match por alias exacto (case-insensitive): alta, pero
# por debajo de 1.0 que se reserva al match por nombre exacto.
ALIAS_CONFIDENCE = 0.9


class Embedder(Protocol):
    """Contrato de embeddings (dimensión configurable). Seam para F2.

    NUNCA se instancia con un proveedor pago dentro de este módulo. La
    implementación real (o una falsa determinista en tests) se INYECTA.
    """

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class Resolved:
    """La entidad extraída corresponde a una existente en el grafo."""

    entity_id: UUID
    confidence: float


@dataclass(frozen=True, slots=True)
class NeedsDisambiguation:
    """Hay candidatos pero ninguno supera el umbral: pregunta a la bandeja."""

    question: str
    candidates: list[UUID]
    extracted: ExtractedEntity


@dataclass(frozen=True, slots=True)
class Unresolved:
    """No hay ningún candidato: el llamador debe tratarla como entidad NUEVA."""

    extracted: ExtractedEntity


# Unión de resultados de la cascada de resolución.
Resolution = Resolved | NeedsDisambiguation | Unresolved


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return num / (na * nb)


class EntityResolver:
    """Resuelve una `ExtractedEntity` contra el grafo. SOLO LECTURA."""

    def __init__(
        self,
        graph: InMemoryGraph,
        embedder: Embedder | None = None,
        threshold: float = CONFIDENCE_THRESHOLD,
    ) -> None:
        self._graph = graph
        self._embedder = embedder
        self._threshold = threshold

    def resolve(self, extracted: ExtractedEntity) -> Resolution:
        kind = extracted.kind
        needle = extracted.name.casefold()
        candidates = self._graph.entities_by_kind(kind)

        # 1) nombre exacto (case-insensitive) → confianza total.
        for rec in candidates:
            if rec.name.casefold() == needle:
                return Resolved(rec.id, 1.0)

        # 2) alias exacto (case-insensitive) → confianza alta.
        for rec in candidates:
            if any(a.casefold() == needle for a in rec.aliases):
                return Resolved(rec.id, ALIAS_CONFIDENCE)

        # 3) vecino más cercano por embedding (solo si hay embedder y candidatos).
        if self._embedder is not None and candidates:
            vectors = self._embedder.embed([extracted.name, *(r.name for r in candidates)])
            query = vectors[0]
            best: EntityRecord | None = None
            best_sim = -1.0
            for rec, vec in zip(candidates, vectors[1:]):
                sim = _cosine(query, vec)
                if sim > best_sim:
                    best_sim = sim
                    best = rec
            if best is not None and best_sim >= self._threshold:
                return Resolved(best.id, best_sim)
            return NeedsDisambiguation(
                question=(
                    f"¿'{extracted.name}' se refiere a alguna entidad conocida "
                    f"de tipo '{kind}'?"
                ),
                candidates=[r.id for r in candidates],
                extracted=extracted,
            )

        # 4) sin match y sin embedder (o sin candidatos): entidad nueva. El
        #    llamador decide crearla; resolve() no escribe.
        return Unresolved(extracted)


class DisambiguationQueue:
    """Bandeja en memoria de desambiguaciones pendientes (sección 11.2).

    Al responder una pregunta, la forma de superficie que había que desambiguar
    se alimenta como alias de la entidad elegida (sección 7 paso 4:
    "las respuestas alimentan aliases"). La escritura del alias se hace por la
    ruta de merge de `graph.upsert_entity`.
    """

    def __init__(self, graph: InMemoryGraph) -> None:
        self._graph = graph
        self._pending: list[NeedsDisambiguation] = []

    def enqueue(self, item: NeedsDisambiguation) -> None:
        self._pending.append(item)

    def pending(self) -> list[NeedsDisambiguation]:
        return list(self._pending)

    def resolve_answer(self, question: str, chosen_entity_id: UUID) -> EntityRecord:
        """Responde una pregunta pendiente eligiendo una entidad.

        Alimenta como alias de la entidad elegida la forma de superficie
        extraída (name y, si difiere, mention), la saca de la bandeja y devuelve
        la entidad actualizada.
        """
        item = next((i for i in self._pending if i.question == question), None)
        if item is None:
            raise ValueError("no hay desambiguación pendiente con esa pregunta")
        chosen = self._graph.get_entity(chosen_entity_id)
        if chosen is None:
            raise ValueError(f"entidad elegida desconocida: {chosen_entity_id}")

        new_aliases = [item.extracted.name]
        mention = item.extracted.mention
        if mention and mention != item.extracted.name:
            new_aliases.append(mention)

        updated = self._graph.upsert_entity(
            chosen.kind,
            chosen.name,
            aliases=new_aliases,
            first_seen_event=chosen.first_seen_event,
        )
        self._pending.remove(item)
        return updated
