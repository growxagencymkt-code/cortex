# ADR 0001 — Event sourcing con store append-only como única fuente de verdad

- Estado: Aceptada
- Fecha: 2026-07-05
- Fase: F0
- Deriva de: SYSTEM_PROMPT principios 1 y 10, secciones 4 y 6.

## Contexto
CORTEX necesita una memoria organizacional confiable y auditable. Las
alternativas eran (a) un modelo mutable (tablas CRUD que se actualizan), (b)
event sourcing (log append-only + vistas derivadas), (c) un grafo dedicado como
verdad primaria.

## Decisión
El log de eventos (`events`) es la única fuente de verdad, append-only. Grafo,
índice semántico y procesos son vistas derivadas, descartables y reconstruibles
con `rebuild --from-events`. Se refuerza en tres capas:
1. Contrato `EventStore` (Protocol) sin `update`/`delete` — sólo `append`,
   `all_events`, `count`. Un test verifica que la superficie pública no expone
   mutación.
2. Modelos Pydantic `frozen=True` (evento inmutable en memoria).
3. Trigger de Postgres `trg_events_append_only` que rechaza UPDATE/DELETE a
   nivel base.
Las correcciones son eventos nuevos `type='correction'` que referencian al
original (`make_correction`), nunca mutaciones.

## Consecuencias
- (+) Auditoría total y reconstrucción determinista de toda vista.
- (+) `InMemoryEventStore` espeja el contrato de Postgres → tests y dev sin DB.
- (−) Toda "edición" cuesta un evento extra; las vistas deben ser reconstruibles
  por diseño (obliga a mantener `rebuild` siempre verde — ya testeado).
- Una sola base Postgres (principio 10); nada de store de eventos dedicado hasta
  que una métrica lo exija.
