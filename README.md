# CORTEX

Cerebro operativo agentivo: event sourcing + memoria organizacional (grafo con
evidencia + índice semántico + procesos) + simulador de agentes. El documento
maestro que gobierna todo el proyecto es **`docs/SYSTEM_PROMPT.md`** — ante
cualquier ambigüedad, ese doc manda.

## Estado por fases (ver SYSTEM_PROMPT §13)

- **F0 — Esqueleto:** log de eventos append-only, migración con el esquema núcleo
  íntegro (§6) + trigger append-only, conectores idempotentes, `cortex ingest`,
  `rebuild --from-events`, API de healthcheck, suite de inyección obligatoria.
- **F1 — Memoria mínima:** extractor v0.1 determinista ($0), grafo con evidencia
  obligatoria, resolución de entidades + desambiguación. Camino LLM listo detrás
  de un seam de inferencia **API-agnóstico** (NVIDIA/Ollama/vLLM por config).
- F2+ retrieval, simulador, agentes: pendientes.

Compuertas verdes hoy: **mypy --strict** limpio y **toda la suite de tests** en
verde (incluye la de inyección obligatoria). Ver CI abajo.

## Requisitos

- Python 3.12+
- PostgreSQL 16 + extensión **pgvector** (vía `docker compose` o instancia
  propia). El dominio corre sin DB (store en memoria) para tests y dev.
- Opcional: Docker Desktop (para el Postgres local del `docker compose`).

## Puesta en marcha en una PC nueva (portable)

El repo se clona y corre. **Un solo comando** deja todo operativo (crea venv,
instala, prepara `.env`, levanta Postgres, migra y carga el corpus de ejemplo):

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

```bash
# Linux / macOS
bash scripts/bootstrap.sh
```

### Paso a paso (equivalente manual)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows (Unix: .venv/bin/python)
cp .env.example .env                               # completar valores locales

docker compose up -d postgres                      # requiere Docker
.venv/Scripts/python -m alembic upgrade head       # aplica el esquema núcleo (§6)
.venv/Scripts/python -m cortex.cli ingest --fixture tests/fixtures/sample_emails.jsonl
.venv/Scripts/python -m cortex.cli rebuild --from-events
```

> **Secretos:** `.env` NUNCA se commitea (está en `.gitignore`). Las credenciales
> (Postgres, y opcional la API key de inferencia) se completan en la PC destino;
> el repo no contiene ni una. Cloná, poné tus valores en `.env`, listo.

## Comandos

```bash
# Tests (incluye la suite de inyección OBLIGATORIA — §9.4)
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m pytest -m injection -q

# Tipado estricto (gate de CI — §5)
.venv/Scripts/python -m mypy

# Ingesta idempotente de un corpus JSONL de mails (seed / import de export propio)
.venv/Scripts/python -m cortex.cli ingest --fixture tests/fixtures/sample_emails.jsonl

# Reconstruir las vistas derivadas desde el log (siempre disponible — principio 1)
.venv/Scripts/python -m cortex.cli rebuild --from-events --store memory

# Levantar la API
.venv/Scripts/python -m uvicorn cortex.api.app:app --port 8000   # GET /health
```

## Inferencia — API-agnóstica (NVIDIA por defecto, creds por afuera)

El seam de inferencia habla el protocolo `/chat/completions` de OpenAI, así que
funciona con **cualquier** endpoint compatible: **NVIDIA NIM**, Ollama local,
vLLM, etc. Cambiar de proveedor es cambiar dos variables de entorno — **cero
código** (ver `docs/decisions/0003`).

```bash
# NVIDIA NIM (proveedor elegido). La API key la inyectás vos; NO va al repo.
CORTEX_INFERENCE_BASE_URL=https://integrate.api.nvidia.com/v1
CORTEX_INFERENCE_API_KEY=nvapi-...            # se completa en la PC destino
CORTEX_FAST_MODEL=meta/llama-3.1-8b-instruct  # extracción masiva / clasificación
CORTEX_CORE_MODEL=meta/llama-3.1-70b-instruct # núcleo / juez del simulador

# Alternativa local gratis (Ollama): sin key
# CORTEX_INFERENCE_BASE_URL=http://127.0.0.1:11434/v1
```

**Regla de costo (innegociable):** sin `CORTEX_INFERENCE_BASE_URL` configurada,
la extracción usa el extractor determinista (costo $0) y el cliente de inferencia
se niega a correr. En dev/CI, por defecto, **no se dispara ninguna llamada paga**.
Los model IDs viven en configuración, jamás en el código (principio 9).

## CI (compuertas de calidad)

`.github/workflows/ci.yml` corre en cada push/PR, sin secretos: `mypy --strict`,
`alembic upgrade head` contra un Postgres pgvector real, seed idempotente,
`pytest` completo y la **suite de inyección OBLIGATORIA** (§9.4). Cualquier
obediencia a una instrucción embebida en contenido observado falla el build.

## Backup / restore de Postgres

Los datos viven en el volumen `cortex_pgdata` (docker compose). Backup:

```bash
docker compose exec -T postgres pg_dump -U cortex cortex | gzip > backups/cortex.sql.gz
gunzip -c backups/cortex.sql.gz | docker compose exec -T postgres psql -U cortex cortex
```

## Decisiones de arquitectura

Registradas en `docs/decisions/` (un ADR de una página por decisión no trivial,
§12).
