"""Esquema núcleo de CORTEX — modelo de datos íntegro de SYSTEM_PROMPT sección 6.

Crea la extensión pgvector, las 9 tablas (events, entities, relations, chunks,
process_cases, agent_specs, simulation_runs, llm_calls, decisions_log) con
todos sus índices y constraints, y el trigger que hace `events` append-only
a nivel base (principio 1: jamás UPDATE/DELETE; correcciones = eventos nuevos).

Revision ID: 0001
Revises: None
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op

from cortex.settings import get_settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Dimensión de embeddings por configuración (sección 5; default 1024, sección 6).
EMBEDDING_DIM = get_settings().embedding_dim


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- events: log append-only, única fuente de verdad ---
    op.execute(
        """
        CREATE TABLE events (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ NOT NULL,
            ingested_at TIMESTAMPTZ DEFAULT now(),
            source TEXT NOT NULL,
            type TEXT NOT NULL,
            external_id TEXT UNIQUE,
            actor TEXT,
            payload JSONB NOT NULL,
            pipeline_ver TEXT NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX ix_events_ts ON events (ts)")
    op.execute("CREATE INDEX ix_events_type_ts ON events (type, ts)")

    # Refuerzo del principio 1 a nivel base: events jamás UPDATE/DELETE.
    op.execute(
        """
        CREATE FUNCTION events_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'events es append-only: % prohibido (correcciones = eventos nuevos type ''correction'')',
                TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_events_append_only
        BEFORE UPDATE OR DELETE ON events
        FOR EACH ROW EXECUTE FUNCTION events_append_only()
        """
    )

    # --- entities ---
    op.execute(
        """
        CREATE TABLE entities (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            aliases TEXT[] DEFAULT '{}',
            attrs JSONB DEFAULT '{}',
            first_seen_event BIGINT REFERENCES events(id),
            UNIQUE (kind, name)
        )
        """
    )

    # --- relations ---
    op.execute(
        """
        CREATE TABLE relations (
            id BIGSERIAL PRIMARY KEY,
            src UUID NOT NULL REFERENCES entities(id),
            rel TEXT NOT NULL,
            dst UUID NOT NULL REFERENCES entities(id),
            evidence_event BIGINT NOT NULL REFERENCES events(id),
            confidence REAL NOT NULL DEFAULT 1.0,
            valid_from TIMESTAMPTZ NOT NULL,
            valid_to TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX ix_relations_src_rel ON relations (src, rel)")
    op.execute("CREATE INDEX ix_relations_dst_rel ON relations (dst, rel)")

    # --- chunks (índice semántico) ---
    op.execute(
        f"""
        CREATE TABLE chunks (
            id BIGSERIAL PRIMARY KEY,
            event_id BIGINT NOT NULL REFERENCES events(id),
            entity_ids UUID[] DEFAULT '{{}}',
            text TEXT NOT NULL,
            embedding VECTOR({EMBEDDING_DIM}),
            embed_model TEXT NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX ix_chunks_entity_ids ON chunks USING GIN (entity_ids)")

    # --- process_cases ---
    op.execute(
        """
        CREATE TABLE process_cases (
            id BIGSERIAL PRIMARY KEY,
            process_id UUID REFERENCES entities(id),
            case_key TEXT NOT NULL,
            event_ids BIGINT[] NOT NULL,
            started_at TIMESTAMPTZ,
            ended_at TIMESTAMPTZ,
            outcome TEXT
        )
        """
    )

    # --- agent_specs ---
    op.execute(
        """
        CREATE TABLE agent_specs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            version INT NOT NULL,
            stage TEXT NOT NULL,
            prompt TEXT NOT NULL,
            tools JSONB NOT NULL,
            triggers JSONB NOT NULL,
            permissions JSONB NOT NULL,
            metrics_gate JSONB NOT NULL,
            created_by TEXT NOT NULL,
            approved_at TIMESTAMPTZ,
            UNIQUE (name, version)
        )
        """
    )

    # --- simulation_runs ---
    op.execute(
        """
        CREATE TABLE simulation_runs (
            id BIGSERIAL PRIMARY KEY,
            agent_spec UUID REFERENCES agent_specs(id),
            window_start TIMESTAMPTZ NOT NULL,
            window_end TIMESTAMPTZ NOT NULL,
            pipeline_ver TEXT NOT NULL,
            results JSONB NOT NULL,
            cases JSONB NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )

    # --- llm_calls (economía visible, principio 8) ---
    op.execute(
        """
        CREATE TABLE llm_calls (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT now(),
            agent TEXT NOT NULL,
            purpose TEXT NOT NULL,
            model TEXT NOT NULL,
            tokens_in INT,
            tokens_out INT,
            cost_usd NUMERIC(10,6)
        )
        """
    )

    # --- decisions_log ---
    op.execute(
        """
        CREATE TABLE decisions_log (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT now(),
            proposal JSONB NOT NULL,
            evidence_events BIGINT[],
            human_choice TEXT NOT NULL,
            human_note TEXT,
            result_event BIGINT REFERENCES events(id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS decisions_log")
    op.execute("DROP TABLE IF EXISTS llm_calls")
    op.execute("DROP TABLE IF EXISTS simulation_runs")
    op.execute("DROP TABLE IF EXISTS agent_specs")
    op.execute("DROP TABLE IF EXISTS process_cases")
    op.execute("DROP TABLE IF EXISTS chunks")
    op.execute("DROP TABLE IF EXISTS relations")
    op.execute("DROP TABLE IF EXISTS entities")
    op.execute("DROP TRIGGER IF EXISTS trg_events_append_only ON events")
    op.execute("DROP FUNCTION IF EXISTS events_append_only()")
    op.execute("DROP TABLE IF EXISTS events")
