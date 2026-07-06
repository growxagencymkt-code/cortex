"""API interna de CORTEX (FastAPI, un solo proceso — sección 5)."""

from cortex.api.app import app, create_app

__all__ = ["app", "create_app"]
