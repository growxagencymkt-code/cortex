"""Grafo de entidades y relaciones con evidencia (sección 6, tablas `entities` y `relations`).

Vista derivada del log de eventos (principio 1): descartable y reconstruible.
Toda afirmación apunta a su `evidence_event` (principio 2): una relación sin
evidencia NO entra a la memoria.

Esta implementación es **en memoria**, DB-agnóstica, y espeja 1:1 el contrato
Postgres de la sección 6 para que la migración a `psycopg`/SQLAlchemy sea directa:

    entities(id UUID PK DEFAULT gen_random_uuid(), kind TEXT, name TEXT,
             aliases TEXT[] DEFAULT '{}', attrs JSONB DEFAULT '{}',
             first_seen_event BIGINT REFERENCES events(id), UNIQUE(kind,name))
    relations(id BIGSERIAL PK, src UUID REFERENCES entities(id), rel TEXT,
              dst UUID REFERENCES entities(id), evidence_event BIGINT NOT NULL
              REFERENCES events(id), confidence REAL DEFAULT 1.0,
              valid_from TIMESTAMPTZ NOT NULL, valid_to TIMESTAMPTZ)

Notas de fidelidad al contrato SQL:
- UNIQUE(kind,name): `upsert_entity` es idempotente por (kind,name) → mismo id.
- El log de eventos es append-only e inmutable; el GRAFO no lo es: `entities` y
  `relations` son vistas derivadas y SÍ se actualizan (UPDATE) — cerrar una
  relación por contradicción (valid_to) y mergear aliases son UPDATE de filas
  derivadas, no mutaciones del log. Solo `events` es intocable (principio 1).
- Los ids de `relations` son un contador monótono (espeja BIGSERIAL).
- Los ids de `entities` se derivan de forma determinista de (kind,name) con
  uuid5 sobre un namespace fijo: misma secuencia de llamadas → mismo grafo,
  incluidos los UUID (más fuerte que lo exigido, que solo pedía estructura
  idéntica).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Iterable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Namespace fijo para derivar UUID de entidad de forma determinista por (kind,name).
# El Postgres real usa gen_random_uuid(); acá elegimos identidad estable por la
# clave única, lo que hace el grafo reproducible sin cambiar el contrato (el id
# sigue siendo un UUID opaco).
_ENTITY_NAMESPACE = UUID("c04e0000-0000-4000-8000-000000000000")


def _entity_id(kind: str, name: str) -> UUID:
    return uuid.uuid5(_ENTITY_NAMESPACE, f"{kind}\x00{name}")


def _dedup_stable(items: Iterable[str]) -> list[str]:
    """Deduplica preservando el orden de primera aparición."""
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


class EntityRecord(BaseModel):
    """Una fila de `entities`. Mutable: espeja UPDATE de una vista derivada
    (merge de aliases). El log de eventos, en cambio, es inmutable."""

    model_config = ConfigDict(validate_assignment=True)

    id: UUID
    kind: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    attrs: dict[str, Any] = Field(default_factory=dict)
    first_seen_event: int


class RelationRecord(BaseModel):
    """Una fila de `relations`. `valid_to` se cierra (UPDATE) cuando una
    relación exclusiva la contradice; la historia nunca se borra."""

    model_config = ConfigDict(validate_assignment=True)

    id: int
    src: UUID
    rel: str
    dst: UUID
    evidence_event: int
    confidence: float = 1.0
    valid_from: datetime
    valid_to: datetime | None = None


class InMemoryGraph:
    """Grafo en memoria de entidades y relaciones con evidencia.

    Mismo contrato que la futura implementación Postgres (sección 6). Se usa en
    F1 (sin base de datos disponible), en tests y para smoke-runs.

    `exclusive_rels`: tipos de relación de valor único por `src` (p. ej.
    {"works_at", "status"}). Al agregar una relación exclusiva para un `src` que
    ya tiene una vigente de ese tipo, se cierra la vigente (valid_to = valid_from
    de la nueva) y se abre la nueva (sección 7, paso 5). Las relaciones NO
    exclusivas coexisten.
    """

    def __init__(self, *, exclusive_rels: frozenset[str] = frozenset()) -> None:
        self._exclusive_rels = exclusive_rels
        self._entities: dict[UUID, EntityRecord] = {}
        self._by_kind_name: dict[tuple[str, str], UUID] = {}
        self._relations: list[RelationRecord] = []
        self._rel_counter: int = 0

    # ----------------------------------------------------------------- entities
    def upsert_entity(
        self,
        kind: str,
        name: str,
        *,
        aliases: Iterable[str] = (),
        attrs: dict[str, Any] | None = None,
        first_seen_event: int,
    ) -> EntityRecord:
        """Inserta o actualiza una entidad respetando UNIQUE(kind,name).

        Un segundo upsert de la misma (kind,name) devuelve la MISMA entidad
        (mismo id) y MERGEA los aliases nuevos (dedup, orden estable). El
        `first_seen_event` queda en el más temprano visto. Los `attrs` provistos
        se mergean sobre los existentes (additivo; no borra claves previas).
        """
        key = (kind, name)
        existing_id = self._by_kind_name.get(key)
        if existing_id is not None:
            rec = self._entities[existing_id]
            merged = _dedup_stable([*rec.aliases, *aliases])
            if merged != rec.aliases:
                rec.aliases = merged
            if first_seen_event < rec.first_seen_event:
                rec.first_seen_event = first_seen_event
            if attrs:
                rec.attrs = {**rec.attrs, **attrs}
            return rec

        rec = EntityRecord(
            id=_entity_id(kind, name),
            kind=kind,
            name=name,
            aliases=_dedup_stable(aliases),
            attrs=dict(attrs) if attrs else {},
            first_seen_event=first_seen_event,
        )
        self._entities[rec.id] = rec
        self._by_kind_name[key] = rec.id
        return rec

    def get_entity(self, entity_id: UUID) -> EntityRecord | None:
        return self._entities.get(entity_id)

    def find_by_name_or_alias(self, kind: str, text: str) -> EntityRecord | None:
        """Busca por nombre O alias exacto (case-insensitive), en orden de
        inserción. Devuelve el primer match, o None."""
        needle = text.casefold()
        for rec in self._entities.values():
            if rec.kind != kind:
                continue
            if rec.name.casefold() == needle:
                return rec
            if any(a.casefold() == needle for a in rec.aliases):
                return rec
        return None

    def entities_by_kind(self, kind: str) -> list[EntityRecord]:
        return [rec for rec in self._entities.values() if rec.kind == kind]

    def entities_all(self) -> list[EntityRecord]:
        """Todas las entidades (orden de inserción). Simétrico a all_relations()."""
        return list(self._entities.values())

    # ---------------------------------------------------------------- relations
    def add_relation(
        self,
        src: UUID,
        rel: str,
        dst: UUID,
        *,
        evidence_event: int | None,
        valid_from: datetime,
        confidence: float = 1.0,
    ) -> RelationRecord:
        """Agrega una relación con evidencia.

        Rechaza (ValueError) si `evidence_event` es None o <= 0: una afirmación
        sin evidencia no entra a la memoria (principio 2; espeja BIGINT NOT NULL
        con FK a events.id, que son >= 1). Rechaza si `src`/`dst` no existen.

        Si `rel` es exclusiva y `src` ya tiene una vigente (valid_to is None) de
        ese tipo, la cierra (valid_to = valid_from) y abre la nueva.
        """
        if evidence_event is None or evidence_event <= 0:
            raise ValueError(
                "evidence_event es obligatorio y debe ser > 0 "
                "(principio 2: sin evidencia no entra a la memoria)"
            )
        if src not in self._entities:
            raise ValueError(f"src desconocido: {src}")
        if dst not in self._entities:
            raise ValueError(f"dst desconocido: {dst}")

        if rel in self._exclusive_rels:
            for r in self._relations:
                if r.src == src and r.rel == rel and r.valid_to is None:
                    r.valid_to = valid_from

        self._rel_counter += 1
        record = RelationRecord(
            id=self._rel_counter,
            src=src,
            rel=rel,
            dst=dst,
            evidence_event=evidence_event,
            confidence=confidence,
            valid_from=valid_from,
            valid_to=None,
        )
        self._relations.append(record)
        return record

    def relations_valid_at(self, src_id: UUID, at: datetime) -> list[RelationRecord]:
        """Relaciones de `src_id` vigentes en el instante `at`:
        valid_from <= at y (valid_to is None o at < valid_to)."""
        return [
            r
            for r in self._relations
            if r.src == src_id
            and r.valid_from <= at
            and (r.valid_to is None or at < r.valid_to)
        ]

    def all_relations(self) -> list[RelationRecord]:
        return list(self._relations)
