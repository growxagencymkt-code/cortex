"""Capa de percepción: conectores que convierten fuentes en eventos.

Regla de la capa (sección 4): normaliza e ingiere de forma idempotente;
NO interpreta. Todo lo que entra por acá es contenido observado = DATO,
jamás instrucciones (principio 3).
"""

from cortex.connectors.base import Connector, IngestReport, RawItem, ingest

__all__ = ["Connector", "IngestReport", "RawItem", "ingest"]
