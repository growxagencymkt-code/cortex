"""Extractor v0.1 — extracción estructurada de UN evento (sección 7, paso 3).

Dos implementaciones detrás de un mismo contrato (`Extractor`):

- `DeterministicExtractor`: reglas puras, SIN modelo, costo $0. Es el extractor
  por defecto de F1 y el que corre en dev/CI. Trata el contenido como DATO:
  detecta hechos por patrón, jamás obedece instrucciones embebidas (principio 3).
- El camino LLM (modelo rápido, sección 5) queda detrás de la interfaz
  `InferenceClient` (extraction/inference.py) y NO se cablea a un proveedor real
  en esta fase: la elección de proveedor es una decisión del fundador
  (ver docs/decisions/0003-proveedor-inferencia.md). En dev/tests se inyecta un
  mock; nunca se dispara inferencia paga sin OK explícito.

Regla de oro del extractor: es una función de contenido→hechos. No tiene efectos
secundarios, no llama herramientas, no ejecuta nada de lo que lea.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Protocol

from cortex.events.models import Event
from cortex.extraction.models import (
    ExtractedCommitment,
    ExtractedDecision,
    ExtractedEntity,
    ExtractedOpenQuestion,
    ExtractedRelation,
    ExtractionResult,
)


class Extractor(Protocol):
    """Contrato de extracción: un evento entra, hechos estructurados salen."""

    def extract(self, event: Event) -> ExtractionResult: ...


# --- Parsing helpers (puros) -------------------------------------------------

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Forma "Display Name <email>": el nombre SOLO existe si hay ángulos. Un address
# pelado (juan@acme.com) cae al fallback y no se le arranca ningún carácter.
_NAME_ADDR_RE = re.compile(r"^\s*(?P<name>.+?)\s*<(?P<email>[^>]+@[^>]+)>\s*$")
# Fechas dd/mm o dd/mm/aaaa (formato Latam). El año 2 dígitos se asume 20xx.
_DATE_RE = re.compile(r"\b(?P<d>\d{1,2})/(?P<m>\d{1,2})(?:/(?P<y>\d{2,4}))?\b")

# Patrones de compromiso (español). Capturan "qué" a groso modo; el detalle fino
# es trabajo del camino LLM en F1.1. Acá: precisión razonable, cero alucinación.
_COMMITMENT_PATTERNS = (
    re.compile(r"\b(?:te|le|les)\s+(?:env[ií]o|mando|paso|entrego|hago llegar)\b(?P<what>[^.\n]*)", re.I),
    re.compile(r"\bme\s+comprometo\s+a\b(?P<what>[^.\n]*)", re.I),
    re.compile(r"\bquedamos\s+en\b(?P<what>[^.\n]*)", re.I),
    re.compile(r"\b(?:voy|vamos)\s+a\s+(?P<what>(?:enviar|mandar|entregar|preparar|revisar|coordinar)[^.\n]*)", re.I),
)
_DECISION_PATTERNS = (
    re.compile(r"\b(?:decidimos|decid[ií]|qued[óo]\s+decidido|vamos\s+con|acordamos)\b(?P<what>[^.\n]*)", re.I),
)


def _as_dict(value: Any) -> dict[str, Any]:
    """Normaliza un `summary` que puede venir como dict o como JSON string."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _as_str_list(value: Any) -> list[str]:
    """Lista de strings no vacíos desde un campo que puede no ser lista."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        s = str(item).strip()
        if s:
            out.append(s)
    return out


def _parse_date(text: str) -> date | None:
    m = _DATE_RE.search(text)
    if m is None:
        return None
    day, month = int(m.group("d")), int(m.group("m"))
    year_raw = m.group("y")
    if year_raw is None:
        return None  # sin año explícito no inventamos uno (principio 2)
    year = int(year_raw)
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _split_name_email(raw: str) -> tuple[str | None, str | None]:
    """De 'Juan Perez <juan@acme.com>' → ('Juan Perez', 'juan@acme.com')."""
    m = _NAME_ADDR_RE.match(raw.strip())
    if m is None:
        found = _EMAIL_RE.search(raw)
        return (None, found.group(0).lower() if found else None)
    name = m.group("name")
    email = m.group("email")
    return (name.strip() if name else None, email.lower() if email else None)


def _org_from_email(email: str) -> str | None:
    """Dominio → nombre de organización tentativo (acme.com → acme.com).

    No mapea dominios de correo genéricos (gmail/outlook/...) a organización.
    """
    domain = email.split("@", 1)[-1].lower()
    generic = {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "proton.me"}
    if domain in generic:
        return None
    return domain


def _person(raw_addr: str) -> tuple[ExtractedEntity, str | None] | None:
    """Construye la entidad person desde un campo from/to. Devuelve (entity, org_domain)."""
    name, email = _split_name_email(raw_addr)
    if email is None:
        return None
    aliases = [name] if name else []
    entity = ExtractedEntity(kind="person", name=email, aliases=aliases, mention=raw_addr.strip())
    return entity, _org_from_email(email)


# --- Extractor determinista --------------------------------------------------


class DeterministicExtractor:
    """Extractor sin modelo (costo $0). Cubre eventos de mail en F1.

    Para tipos de evento aún no soportados devuelve un resultado vacío: nunca
    inventa hechos sin evidencia en el contenido (principio 2).
    """

    def extract(self, event: Event) -> ExtractionResult:
        if event.type == "email.received":
            return self._extract_email(event)
        if event.type == "meeting.transcript":
            return self._extract_meeting(event)
        return ExtractionResult()

    def _extract_meeting(self, event: Event) -> ExtractionResult:
        """Extrae hechos de una reunión del Copiloto (title/topic/summary/transcript).

        La reunión y su tema entran como entidades (con relación `about`); las
        acciones del resumen y los patrones del transcript, como compromisos; las
        decisiones del resumen y del transcript, como decisiones. Todo es DATO
        observado (principio 3): no se obedece nada del transcript.
        """
        payload = event.payload
        entities: list[ExtractedEntity] = []
        relations: list[ExtractedRelation] = []
        seen: set[str] = set()

        def add_entity(ent: ExtractedEntity) -> None:
            if ent.name not in seen:
                seen.add(ent.name)
                entities.append(ent)

        title = str(payload.get("title") or "").strip()
        topic = str(payload.get("topic") or "").strip()
        user = str(payload.get("user") or "").strip() or "desconocido"

        if title:
            add_entity(ExtractedEntity(kind="meeting", name=title, mention=title))
        if topic:
            add_entity(ExtractedEntity(kind="topic", name=topic, mention=topic))
            if title:
                relations.append(
                    ExtractedRelation(
                        src_name=title, src_kind="meeting",
                        rel="about", dst_name=topic, dst_kind="topic",
                    )
                )

        summary = _as_dict(payload.get("summary"))
        transcript = str(payload.get("transcript") or "")

        commitments: list[ExtractedCommitment] = []
        for accion in _as_str_list(summary.get("acciones")):
            commitments.append(
                ExtractedCommitment(who=user, what=accion[:280], direction="unknown", confidence=0.75)
            )
        commitments.extend(self._commitments(transcript, who=user))

        decisions: list[ExtractedDecision] = []
        for dec in _as_str_list(summary.get("decisiones")):
            decisions.append(ExtractedDecision(statement=dec[:280], made_by=user, confidence=0.75))
        decisions.extend(self._decisions(transcript, made_by=user))

        return ExtractionResult(
            entities=entities,
            relations=relations,
            commitments=commitments,
            decisions=decisions,
            open_questions=self._open_questions(transcript),
        )

    def _extract_email(self, event: Event) -> ExtractionResult:
        payload = event.payload
        entities: list[ExtractedEntity] = []
        relations: list[ExtractedRelation] = []
        seen_entity_names: set[str] = set()

        def add_entity(ent: ExtractedEntity) -> None:
            if ent.name not in seen_entity_names:
                seen_entity_names.add(ent.name)
                entities.append(ent)

        sender_result = _person(str(payload.get("from", "")))
        sender_name: str | None = None
        if sender_result is not None:
            sender_entity, sender_org = sender_result
            sender_name = sender_entity.name
            add_entity(sender_entity)
            if sender_org is not None:
                add_entity(ExtractedEntity(kind="org", name=sender_org, mention=sender_org))
                relations.append(
                    ExtractedRelation(
                        src_name=sender_entity.name, src_kind="person",
                        rel="member_of", dst_name=sender_org, dst_kind="org",
                    )
                )

        # Destinatarios (to puede ser string o lista).
        raw_to = payload.get("to", "")
        to_fields = raw_to if isinstance(raw_to, list) else [raw_to]
        for raw_to_addr in to_fields:
            recipient_result = _person(str(raw_to_addr))
            if recipient_result is None:
                continue
            recipient_entity, recipient_org = recipient_result
            add_entity(recipient_entity)
            if recipient_org is not None:
                add_entity(ExtractedEntity(kind="org", name=recipient_org, mention=recipient_org))
            if sender_name is not None and recipient_entity.name != sender_name:
                relations.append(
                    ExtractedRelation(
                        src_name=sender_name, src_kind="person",
                        rel="emailed", dst_name=recipient_entity.name, dst_kind="person",
                    )
                )

        body = str(payload.get("body", ""))
        commitments = self._commitments(body, who=sender_name or "desconocido")
        decisions = self._decisions(body, made_by=sender_name)
        open_questions = self._open_questions(body)

        return ExtractionResult(
            entities=entities,
            relations=relations,
            commitments=commitments,
            decisions=decisions,
            open_questions=open_questions,
        )

    @staticmethod
    def _commitments(body: str, *, who: str) -> list[ExtractedCommitment]:
        out: list[ExtractedCommitment] = []
        for pattern in _COMMITMENT_PATTERNS:
            for m in pattern.finditer(body):
                what = m.group("what").strip(" .:,-") if m.group("what") else m.group(0).strip()
                if not what:
                    continue
                out.append(
                    ExtractedCommitment(
                        who=who,
                        what=what[:280],
                        due=_parse_date(m.group(0)),
                        direction="unknown",
                        confidence=0.8,
                    )
                )
        return out

    @staticmethod
    def _decisions(body: str, *, made_by: str | None) -> list[ExtractedDecision]:
        out: list[ExtractedDecision] = []
        for pattern in _DECISION_PATTERNS:
            for m in pattern.finditer(body):
                what = m.group("what").strip(" .:,-") if m.group("what") else ""
                if not what:
                    continue
                out.append(ExtractedDecision(statement=what[:280], made_by=made_by, confidence=0.8))
        return out

    @staticmethod
    def _open_questions(body: str) -> list[ExtractedOpenQuestion]:
        out: list[ExtractedOpenQuestion] = []
        for sentence in re.split(r"(?<=[.?!\n])\s+", body):
            s = sentence.strip()
            if s.endswith("?") and len(s) > 8:
                out.append(ExtractedOpenQuestion(question=s[:280], confidence=0.7))
        return out
