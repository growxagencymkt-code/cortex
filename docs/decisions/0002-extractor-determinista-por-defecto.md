# ADR 0002 — Extractor determinista ($0) como extractor por defecto de F1

- Estado: Aceptada
- Fecha: 2026-07-05
- Fase: F1
- Deriva de: SYSTEM_PROMPT sección 7 (paso 3), sección 5, principios 2, 3, 8;
  regla de costo del ecosistema (no gastar en APIs pagas en dev).

## Contexto
La extracción estructurada (entidades, relaciones, compromisos, decisiones,
preguntas) es el paso 3 del pipeline. La sección 5 propone un "modelo rápido"
(Haiku/Sonnet) para extracción masiva. Pero: (a) el ecosistema migró OFF de APIs
pagas y no se debe gastar en inferencia durante el desarrollo; (b) necesitamos un
extractor reproducible para que `rebuild --from-events` sea determinista y
testeable; (c) todavía no hay proveedor de inferencia elegido (ver ADR 0003).

## Decisión
El extractor por defecto de F1 es `DeterministicExtractor`: reglas puras, sin
modelo, costo $0. Cubre eventos de mail (entidades del sobre, relaciones
`emailed`/`member_of`, compromisos/decisiones/preguntas por patrón). El camino
LLM (`LLMExtractor`) existe detrás de un seam de inferencia inyectable, pero su
cliente por defecto se niega a correr y en tests se inyecta un cliente estático.

Regla de oro: el extractor es una función contenido→hechos, sin efectos
secundarios. No ejecuta nada de lo que lee (principio 3): por construcción no
puede obedecer instrucciones embebidas — su tipo de salida no tiene campo de
acción.

## Consecuencias
- (+) `rebuild` determinista y CI sin costo ni red.
- (+) Injection-safe por diseño; base natural de la suite de inyección.
- (+) Cuando el fundador elija proveedor (ADR 0003), el `LLMExtractor` ya está
  cableado por inyección: se enchufa sin tocar el pipeline.
- (−) La cobertura del determinista es acotada (patrones en español, mail
  primero). El LLM mejorará recall en F1.1; hasta entonces, precisión > recall
  (no inventar, principio 2).
