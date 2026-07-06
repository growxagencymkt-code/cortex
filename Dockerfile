FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
# SPA de operador ya compilada (web/dist). La API la sirve same-origin en /.
COPY web/dist ./web/dist

RUN pip install .

EXPOSE 8000

# Aplica migraciones y levanta la API (un solo proceso, sección 5 del SYSTEM_PROMPT).
# Bindea $PORT si la plataforma lo inyecta (Railway/Render); si no, 8000 local.
CMD ["sh", "-c", "alembic upgrade head && uvicorn cortex.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
