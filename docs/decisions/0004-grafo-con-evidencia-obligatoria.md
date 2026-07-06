# ADR 0004 — Grafo con evidencia obligatoria y contradicciones bitemporales

- Estado: Aceptada
- Fecha: 2026-07-05
- Fase: F1
- Deriva de: SYSTEM_PROMPT principios 1 y 2, secciones 6 y 7 (paso 5).

## Contexto
La memoria de grafo (entities/relations) es una vista derivada del log. El
principio 2 es tajante: "una afirmación sin `evidence_event` no entra a la
memoria". Además (sección 7 paso 5) las contradicciones no se sobrescriben:
cierran la relación vigente (`valid_to = ts`) y abren una nueva.

## Decisión
`InMemoryGraph` (que espeja las tablas de la sección 6 para mapear 1:1 a Postgres
después):
- `add_relation` **exige** `evidence_event` válido (> 0); rechaza `None`/`<=0`
  con error. Es imposible escribir una relación sin evidencia.
- Cada relación lleva `confidence`, `valid_from`, `valid_to` (bitemporalidad de
  validez). `relations_valid_at(src, t)` devuelve lo vigente a la fecha `t`
  (necesario para snapshots temporales del simulador, F3 — evitar fuga temporal).
- Contradicciones: para rel types declarados exclusivos (single-valued, p.ej.
  `works_at`), agregar uno nuevo cierra el vigente y abre el nuevo; los no
  exclusivos coexisten. Nunca se muta/borra historia.
- Entidades: `UNIQUE(kind,name)`; re-upsert fusiona aliases (order-stable, dedup)
  y conserva el `first_seen_event` más antiguo.

## Consecuencias
- (+) Toda relación es trazable a su evento de origen → confianza por
  trazabilidad (sección 11), y el grafo es 100% reconstruible por `rebuild`.
- (+) La validez temporal habilita los snapshots del simulador sin rediseño.
- (−) El caller (pipeline de ingesta / rebuild) es responsable de pasar el
  `evidence_event = event.id`; se cubre con tests de integración.
- Implementación in-memory ahora (no hay Postgres en la máquina); el contrato es
  idéntico al DDL, así que la versión Postgres es una traducción directa.
