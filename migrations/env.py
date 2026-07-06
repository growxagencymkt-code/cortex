"""Entorno Alembic de CORTEX.

El DSN sale de cortex.settings (única puerta a configuración). Soporta:
- modo online: aplica migraciones contra el Postgres configurado
- modo offline (--sql): emite el DDL sin necesidad de base (verificación)
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from cortex.settings import get_settings

config = context.config

# Sin autogenerate en F0: las migraciones se escriben a mano (DDL canónico).
target_metadata = None


def _dsn() -> str:
    override = config.get_main_option("sqlalchemy.url")
    if override:
        return override
    return get_settings().postgres_dsn


def run_migrations_offline() -> None:
    context.configure(
        url=_dsn(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        dialect_name="postgresql",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_dsn())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
