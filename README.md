# CORTEX

Cerebro operativo agentivo: event sourcing + memoria organizacional (grafo con
evidencia + índice semántico + procesos) + simulador de agentes. El documento
maestro que gobierna todo el proyecto es **`docs/SYSTEM_PROMPT.md`** — ante
cualquier ambigüedad, ese doc manda.

## Estado por fases (ver SYSTEM_PROMPT §13)

- **F0 — Esqueleto:** log de eventos append-only, migración con el esquema núcleo
  íntegro (§6), conector de mail idempotente, `rebuild --from-events`, API de
  healthcheck, suite de inyección obligatoria. Código listo; **falta aplicar la
  migración contra un Postgres real e ingerir el histórico de mail** (bloqueado
  por infra y credenciales — ver Bloqueos).
- **F1 — Memoria mínima (en curso):** extractor v0.1 determinista ($0), grafo con
  evidencia obligatoria, resolución de entidades + desambiguación.
- F2+ retrieval, simulador, agentes: pendientes.

## Requisitos

- Python 3.12+
- PostgreSQL 16 + extensión **pgvector** (vía `docker compose` o instancia
  propia). El dominio corre sin DB (store en memoria) para tests y dev.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows
cp .env.example .env                               # completar valores locales
```

### Base de datos (cuando haya Docker/Postgres disponible)

```bash
docker compose up -d postgres
.venv/Scripts/python -m alembic upgrade head
```

## Comandos

```bash
# Tests (incluye la suite de inyección OBLIGATORIA — §9.4)
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m pytest -m injection -q

# Tipado estricto (gate de CI — §5)
.venv/Scripts/python -m mypy

# Reconstruir las vistas derivadas desde el log (siempre disponible — principio 1)
.venv/Scripts/python -m cortex.cli rebuild --from-events --store memory
```

## Regla de costo (innegociable)

El ecosistema migró OFF de APIs pagas. En dev/CI **no se dispara inferencia
paga**: el extractor por defecto es determinista (costo $0) y el seam de
inferencia (`extraction/inference.py`) se niega a correr sin un proveedor
elegido explícitamente por el fundador (ver `docs/decisions/0003-*`). Los model
IDs viven en configuración, jamás en el código (principio 9).

## Bloqueos actuales (para el fundador)

1. **Infra Postgres:** esta máquina no tiene Docker ni un Postgres 16+pgvector
   accesible. Hace falta uno para aplicar la migración e ingerir mail real.
2. **Credenciales Gmail:** el `GmailConnector` es un stub; la ingesta real
   necesita OAuth/IMAP del fundador (vía configuración, nunca en el código).
3. **Proveedor de inferencia:** decisión pendiente (ADR 0003) — Anthropic (§5)
   vs stack local gratis (Ollama/NIM) vs híbrido.

## Decisiones de arquitectura

Registradas en `docs/decisions/` (un ADR de una página por decisión no trivial,
§12).
