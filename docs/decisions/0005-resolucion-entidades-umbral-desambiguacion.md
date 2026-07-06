# ADR 0005 — Resolución de entidades en cascada y umbral de desambiguación

- Estado: Aceptada
- Fecha: 2026-07-05
- Fase: F1
- Deriva de: SYSTEM_PROMPT sección 7 (paso 4), sección 6 (regla confidence<0.8),
  sección 11.2 (bandeja de desambiguación).

## Contexto
Antes de escribir al grafo hay que resolver cada entidad extraída contra las
existentes (sección 7 paso 4): exacto → embedding → LLM → si `confidence < 0.8`,
pregunta humana en la bandeja. Escribir una entidad ambigua directo contamina la
memoria.

## Decisión
`EntityResolver.resolve(extracted)` es **read-only** (no escribe al grafo; el
caller decide) y devuelve uno de tres resultados:
- `Resolved(entity_id, confidence)`: match por nombre exacto (`(kind,name)`) o por
  alias, o vecino por embedding con `sim >= 0.8`.
- `NeedsDisambiguation(question, candidates, extracted)`: hay candidatos pero el
  mejor queda por debajo de `0.8` → va a la `DisambiguationQueue` (bandeja), no se
  escribe.
- `Unresolved(extracted)`: no hay candidato → el caller la trata como entidad
  nueva (la crea con `upsert_entity`). Se distingue de la desambiguación: "no la
  conozco" ≠ "no sé cuál de estas es".

`CONFIDENCE_THRESHOLD = 0.8` (constante, coincide con la regla de la sección 6).
El `Embedder` es un Protocol inyectable; en F1 el default es `None` (sin
embeddings — no se llama a ningún proveedor, regla de costo). El salto por
embedding se activa en F2. Responder una desambiguación alimenta el alias elegido
de vuelta a la entidad (`upsert_entity` merge), mejorando la resolución futura.

## Consecuencias
- (+) La memoria no se contamina con entidades ambiguas; el humano decide con
  evidencia (principio 7).
- (+) Separar `Unresolved` de `NeedsDisambiguation` mantiene la escritura de
  entidades nuevas barata y explícita, sin preguntas espurias.
- (−) En F1 sin embedder, la resolución es exacto/alias: dos nombres distintos
  de la misma persona quedan como entidades separadas hasta que un alias o una
  desambiguación (F2 con embeddings) las una. Aceptable: precisión > recall.
