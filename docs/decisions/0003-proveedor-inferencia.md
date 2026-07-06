# ADR 0003 — Proveedor de inferencia: seam API-agnóstico, NVIDIA elegido

- Estado: ACEPTADA (2026-07-05) — dirección del fundador vía AXIS
- Fecha: 2026-07-05
- Fase: F1 (habilita F1.1 / F3)
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
Se adopta un **cliente de inferencia API-agnóstico** que habla el protocolo
`/chat/completions` de OpenAI (`OpenAICompatibleInferenceClient`, en
`extraction/providers.py`). El **proveedor elegido es NVIDIA** (NIM,
`https://integrate.api.nvidia.com/v1`); cambiar a Ollama local, vLLM u otro es
sólo cambiar `CORTEX_INFERENCE_BASE_URL` + `CORTEX_*_MODEL` en configuración —
cero cambios de código. Esto materializa la opción 3 (híbrido) del modo más
flexible posible: un mismo seam sirve local-gratis y frontier-pago según qué
`base_url`/`model` se configure por rol (`fast` vs `core`, ruteo por costo §5).

Invariantes que se mantienen:
- **Credenciales desde afuera, nunca en el repo.** `base_url`, `api_key` y model
  IDs viven en entorno/`settings.py` (principio 9). El código no contiene ninguna
  URL, key ni model id. La `nvapi-...` la inyecta el fundador en la PC destino.
- **Regla de costo intacta.** Sin `CORTEX_INFERENCE_BASE_URL` (+ model del rol),
  `build_inference_client()` devuelve `UnconfiguredInferenceClient` (se niega a
  correr) y el extractor por defecto sigue siendo el determinista (ADR 0002). En
  dev/CI, costo $0 por defecto: no hay ninguna llamada paga hasta que el fundador
  configure el proveedor explícitamente.

## Consecuencias
- El seam está construido y probado sin red (transporte HTTP inyectable; ver
  `tests/test_inference_provider.py`). Activar inferencia real es setear 3 env
  vars; cero cambios en el pipeline.
- F1.1 (extractor LLM en vivo) y F3 (juez del simulador) quedan **desbloqueados**
  en su parte de inferencia: enchufan `build_inference_client(role=...)`.
- Falta sólo la validación de calidad: confirmar que el modelo NVIDIA elegido
  alcanza las compuertas del simulador (§9.3) antes de F3; si no, subir el `core`
  a un modelo más grande — vía config, sin tocar código.
