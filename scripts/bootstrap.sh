#!/usr/bin/env bash
# CORTEX — bootstrap para una PC nueva (Linux / macOS).
# Deja el proyecto listo para correr: venv, deps, .env, Postgres, migración, seed.
# Requisitos previos: Python 3.12+ y Docker instalados y corriendo.
#
# Uso:  bash scripts/bootstrap.sh
#
# NO toca credenciales de inferencia: la API key de NVIDIA (u otro proveedor) la
# completás vos en .env después. Sin ella, el sistema corre igual (extractor $0).
set -euo pipefail
cd "$(dirname "$0")/.."  # raíz del repo

PY=.venv/bin/python

echo "==> 1/6  Creando entorno virtual (.venv)"
[ -d .venv ] || python3 -m venv .venv

echo "==> 2/6  Instalando CORTEX + dependencias de dev"
"$PY" -m pip install --upgrade pip >/dev/null
"$PY" -m pip install -e ".[dev]"

echo "==> 3/6  Preparando .env (si no existe)"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    .env creado desde .env.example — completá tus valores (Postgres, y opcional NVIDIA)."
else
  echo "    .env ya existe, no se toca."
fi

echo "==> 4/6  Levantando Postgres (docker compose)"
docker compose up -d postgres
echo "    Esperando a que Postgres esté healthy..."
for _ in $(seq 1 20); do
  state="$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q postgres)" 2>/dev/null || echo starting)"
  [ "$state" = "healthy" ] && break
  sleep 3
done
[ "${state:-}" = "healthy" ] || { echo "Postgres no llegó a healthy a tiempo."; exit 1; }

echo "==> 5/6  Aplicando migraciones (esquema núcleo)"
"$PY" -m alembic upgrade head

echo "==> 6/6  Cargando corpus de ejemplo (idempotente) y reconstruyendo el grafo"
"$PY" -m cortex.cli ingest --fixture tests/fixtures/sample_emails.jsonl
"$PY" -m cortex.cli rebuild --from-events

echo ""
echo "LISTO. CORTEX quedó operativo en esta PC."
echo "  - Correr la API:   $PY -m uvicorn cortex.api.app:app --port 8000"
echo "  - Correr tests:    $PY -m pytest -q"
echo "  - Inferencia NVIDIA (opcional): completá CORTEX_INFERENCE_* en .env"
