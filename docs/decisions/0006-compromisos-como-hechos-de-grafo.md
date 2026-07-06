# ADR 0006 — Compromisos como hechos de grafo con evidencia

- Estado: Aceptada
- Fecha: 2026-07-05
- Fase: F1
- Deriva de: SYSTEM_PROMPT sección 6 (modelo de datos), sección 7 (paso 3),
  sección 11.3 (panel de compromisos), principios 1 y 2.

## Contexto
El extractor produce `commitments` (sección 7 paso 3) y la aceptación F1 exige
responder "¿qué compromisos vencen esta semana?". Pero el modelo de datos de la
sección 6 NO tiene una tabla `commitments`: sólo events, entities, relations,
chunks, process_cases, agent_specs, etc. ¿Dónde viven los compromisos?

## Decisión
Un compromiso se materializa como un hecho del grafo con evidencia, sin agregar
tablas nuevas (principio 10, simplicidad):
- una **entidad** `kind='commitment'`, con `name` = clave estable
  (`who \x00 what \x00 due`) para respetar `UNIQUE(kind,name)` e idempotencia en
  rebuild, y `attrs = {what, due (ISO|null), direction, confidence}`.
- una **relación** `(persona)-[committed]->(commitment)` con `evidence_event` =
  id del evento del que se extrajo (principio 2). El vencimiento vive en `attrs`
  del compromiso; la query `commitments_due_between` filtra por `due`.

Sólo cuentan como "vencen" los compromisos con fecha explícita (principio 2: no
se inventa un vencimiento que el texto no dice).

## Consecuencias
- (+) Compromisos trazables a su evento, reconstruibles por `rebuild`, sin tocar
  el esquema. El panel de compromisos (11.3) y la aceptación F1 se apoyan en esto.
- (+) La dirección (`owed_by_me`/`owed_to_me`/`unknown`) queda registrada para el
  panel "en dos direcciones"; hoy el extractor determinista la deja en `unknown`
  (no hardcodea quién es el fundador — principio 9). Afinarla es trabajo de F1.1
  (config del buzón propio) o del camino LLM.
- (−) Al ser entidades, dos redacciones distintas del mismo compromiso podrían no
  deduplicar; aceptable en F1 (precisión > recall). Decisiones y preguntas
  abiertas todavía se extraen pero NO se materializan en grafo: se difiere a F1.1
  para no sobre-construir esta sesión.
