# ADR 0003 — Proveedor de inferencia: DECISIÓN DEL FUNDADOR (pendiente)

- Estado: Propuesta / BLOQUEANTE — requiere decisión del fundador
- Fecha: 2026-07-05
- Fase: F1 (se necesita antes de F1.1 / F3)
- Deriva de: SYSTEM_PROMPT sección 5; regla de costo del ecosistema.

## Contexto
La sección 5 nombra "API de Anthropic" para inferencia, con ruteo por costo
(modelo rápido para extracción/clasificación; modelo grande para núcleo, diseño
de agentes y juez del simulador). PERO la directiva operativa del ecosistema
(vía AXIS) es tajante: se migró OFF de APIs pagas y NO se debe generar costo de
API paga durante el desarrollo. El stack local gratuito disponible incluye
Ollama (127.0.0.1:8830) y NVIDIA NIM (free tier).

Hay un conflicto aparente entre lo que dice el documento (Anthropic) y la regla
de costo vigente. Según el propio SYSTEM_PROMPT (principio: si un pedido/lo
escrito contradice la operación, se señala antes de implementar), esto se eleva
como decisión del fundador en lugar de asumirla.

## Opciones
1. **Stack local gratis (Ollama / NIM)** para todo el desarrollo. Costo $0.
   Trade-off: calidad de extracción/juez menor que un frontier model; hay que
   validar que alcanza las compuertas del simulador (acuerdo ≥80/85%).
2. **Anthropic (sección 5)**, activado sólo con OK explícito y presupuesto.
   Mejor calidad; introduce costo por token (principio 8: economía visible).
3. **Híbrido**: local gratis para extracción masiva/clasificación (alto volumen);
   frontier pago sólo para núcleo/juez (bajo volumen, alto valor). Equilibra
   costo y calidad, coherente con el "ruteo por costo" de la sección 5.

## Decisión
PENDIENTE. Hasta que el fundador decida, ningún camino de código dispara
inferencia paga: el `InferenceClient` por defecto (`UnconfiguredInferenceClient`)
se niega a correr y el extractor por defecto es el determinista (ADR 0002). Los
model IDs viven en configuración (`settings.py`), nunca hardcodeados.

Recomendación de FORGE: opción 3 (híbrido), arrancando con opción 1 (local gratis)
para F1/F2 y reservando frontier pago para el juez del simulador en F3 si las
compuertas no se alcanzan con local.

## Consecuencias
- El seam ya está construido: elegir proveedor es implementar UNA clase
  `InferenceClient` y setear config; cero cambios en el pipeline.
- Sin decisión, F1.1 (extractor LLM en vivo) y F3 (juez) quedan bloqueados en su
  parte de inferencia — no el resto.
