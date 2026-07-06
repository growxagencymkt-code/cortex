# CORTEX — bootstrap para una PC nueva (Windows / PowerShell).
# Deja el proyecto listo para correr: venv, deps, .env, Postgres, migración, seed.
# Requisitos previos: Python 3.12+ y Docker Desktop instalados y corriendo.
#
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
#
# NO toca credenciales de inferencia: la API key de NVIDIA (u otro proveedor) la
# completás vos en .env después. Sin ella, el sistema corre igual (extractor $0).

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)  # raíz del repo

Write-Host "==> 1/6  Creando entorno virtual (.venv)"
if (-not (Test-Path ".venv")) { python -m venv .venv }

Write-Host "==> 2/6  Instalando CORTEX + dependencias de dev"
.\.venv\Scripts\python -m pip install --upgrade pip | Out-Null
.\.venv\Scripts\python -m pip install -e ".[dev]"

Write-Host "==> 3/6  Preparando .env (si no existe)"
if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "    .env creado desde .env.example — completá tus valores (Postgres, y opcional NVIDIA)."
} else {
  Write-Host "    .env ya existe, no se toca."
}

Write-Host "==> 4/6  Levantando Postgres (docker compose)"
docker compose up -d postgres

Write-Host "    Esperando a que Postgres esté healthy..."
$deadline = (Get-Date).AddMinutes(1)
do {
  Start-Sleep -Seconds 3
  $state = (docker inspect --format '{{.State.Health.Status}}' (docker compose ps -q postgres) 2>$null)
} while ($state -ne "healthy" -and (Get-Date) -lt $deadline)
if ($state -ne "healthy") { throw "Postgres no llegó a healthy a tiempo." }

Write-Host "==> 5/6  Aplicando migraciones (esquema núcleo)"
.\.venv\Scripts\python -m alembic upgrade head

Write-Host "==> 6/6  Cargando corpus de ejemplo (idempotente) y reconstruyendo el grafo"
.\.venv\Scripts\python -m cortex.cli ingest --fixture tests\fixtures\sample_emails.jsonl
.\.venv\Scripts\python -m cortex.cli rebuild --from-events

Write-Host ""
Write-Host "LISTO. CORTEX quedó operativo en esta PC."
Write-Host "  - Correr la API:   .\.venv\Scripts\python -m uvicorn cortex.api.app:app --port 8000"
Write-Host "  - Correr tests:    .\.venv\Scripts\python -m pytest -q"
Write-Host "  - Inferencia NVIDIA (opcional): completá CORTEX_INFERENCE_* en .env"
