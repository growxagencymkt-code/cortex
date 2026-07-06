"""Única puerta de entrada a configuración y entorno.

Ningún otro módulo lee os.environ ni archivos .env directamente.
Los model IDs, la dimensión de embeddings, el DSN de Postgres y todo lo
específico del despliegue viven acá (principio 9: nada hardcodeado).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_DSN = "postgresql+psycopg://cortex:cortex@localhost:5432/cortex"


def _normalize_dsn(url: str) -> str:
    """Normaliza un DSN de Postgres al driver psycopg que usa SQLAlchemy.

    Plataformas como Railway/Render/Heroku inyectan `DATABASE_URL` con esquema
    `postgres://` o `postgresql://` (sin driver). SQLAlchemy + psycopg3 necesita
    `postgresql+psycopg://`. Esta función lo adapta sin tocar credenciales.
    """
    if url.startswith("postgresql+"):
        return url  # ya trae driver explícito (p.ej. +psycopg)
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


class Settings(BaseSettings):
    """Configuración de CORTEX, leída de variables de entorno / .env (prefijo CORTEX_)."""

    model_config = SettingsConfigDict(
        env_prefix="CORTEX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Base de datos (un solo Postgres para todo — principio 10).
    # Acepta `CORTEX_POSTGRES_DSN` o, si no está, la `DATABASE_URL` que inyectan
    # las plataformas cloud (Railway/Render/Heroku): se normaliza el driver.
    postgres_dsn: str = Field(
        default=_DEFAULT_DSN,
        validation_alias=AliasChoices("CORTEX_POSTGRES_DSN", "DATABASE_URL"),
    )

    @model_validator(mode="after")
    def _normalize_postgres_dsn(self) -> "Settings":
        object.__setattr__(self, "postgres_dsn", _normalize_dsn(self.postgres_dsn))
        return self

    # Pipeline de ingesta: versión semver estampada en cada evento (sección 7)
    pipeline_ver: str = "0.1.0"

    # Embeddings (sección 5: interfaz Embedder propia, dimensión 1024)
    embedding_dim: int = 1024
    embed_model: str = ""  # se define por config en F2; se registra en cada chunk

    # Inferencia (F1+). API-agnóstica: cualquier endpoint compatible con OpenAI
    # (NVIDIA NIM, Ollama, vLLM, ...). Todo vive en config/entorno, jamás en código.
    # Cambiar de proveedor = cambiar base_url + model. Sin base_url no hay cliente
    # real (regla de costo): la extracción cae al determinista ($0).
    inference_base_url: str = ""  # p.ej. https://integrate.api.nvidia.com/v1
    inference_api_key: str = ""  # se inyecta por entorno; NUNCA se commitea
    fast_model: str = ""  # extracción masiva / clasificación
    core_model: str = ""  # núcleo cognitivo / diseño de agentes / juez del simulador

    # API interna
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Interfaz de operador (SPA compilada, §11). Ruta relativa al CWD del proceso
    # (en el contenedor, /app → /app/web/dist). Si no existe, la raíz cae a la
    # página de estado. Se sirve same-origin: la SPA llama /api/* y /health.
    web_dist_dir: str = "web/dist"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Instancia cacheada de Settings (una sola lectura de entorno por proceso)."""
    return Settings()
