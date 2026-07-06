"""Contratos de la extracción estructurada (sección 7, paso 3).

Un extractor lee UN evento del log y devuelve un `ExtractionResult` validado
por Pydantic: entities, relations, commitments, decisions, open_questions.

Principio 3 (contenido observado ≠ instrucciones): estos contratos describen
DATOS extraídos del contenido, jamás acciones a ejecutar. Un extractor nunca
produce "hacé X"; produce "el texto afirma X, con esta evidencia". La
evidencia (el `event.id` del que salió cada afirmación) la estampa el pipeline
al escribir al grafo, no el extractor (principio 2).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

# Clases de entidad reconocidas en F1 (ontología modular; se amplía por config).
ENTITY_KINDS: frozenset[str] = frozenset(
    {"person", "org", "project", "topic", "document", "meeting"}
)

# Dirección de un compromiso (Panel de compromisos en dos direcciones, 11.3).
COMMITMENT_DIRECTIONS: frozenset[str] = frozenset({"owed_by_me", "owed_to_me", "unknown"})


class ExtractedEntity(BaseModel):
    """Una entidad mencionada en el contenido de un evento.

    `mention` conserva la forma de superficie EXACTA hallada en el texto: es la
    traza hacia la evidencia (el pipeline la usa para alimentar aliases en la
    resolución, sección 7 paso 4).
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    mention: str = ""


class ExtractedRelation(BaseModel):
    """Una relación afirmada entre dos entidades (por nombre+kind, sin resolver).

    El pipeline resuelve `src`/`dst` a UUIDs y estampa `evidence_event` al
    escribir al grafo. Sin evidencia, no entra a la memoria (principio 2).
    """

    model_config = ConfigDict(frozen=True)

    src_name: str
    src_kind: str
    rel: str
    dst_name: str
    dst_kind: str
    confidence: float = 1.0


class ExtractedCommitment(BaseModel):
    """Un compromiso detectado (quién debe qué a quién, y para cuándo)."""

    model_config = ConfigDict(frozen=True)

    who: str
    what: str
    due: date | None = None
    direction: str = "unknown"
    confidence: float = 1.0


class ExtractedDecision(BaseModel):
    """Una decisión afirmada en el contenido."""

    model_config = ConfigDict(frozen=True)

    statement: str
    made_by: str | None = None
    confidence: float = 1.0


class ExtractedOpenQuestion(BaseModel):
    """Una pregunta abierta / pendiente detectada en el contenido."""

    model_config = ConfigDict(frozen=True)

    question: str
    confidence: float = 1.0


class ExtractionResult(BaseModel):
    """Salida estructurada y validada de extraer UN evento (sección 7, paso 3)."""

    model_config = ConfigDict(frozen=True)

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    commitments: list[ExtractedCommitment] = Field(default_factory=list)
    decisions: list[ExtractedDecision] = Field(default_factory=list)
    open_questions: list[ExtractedOpenQuestion] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.entities
            or self.relations
            or self.commitments
            or self.decisions
            or self.open_questions
        )
