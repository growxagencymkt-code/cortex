"""Gobernanza transversal: permisos, auditoría, costos, evaluación.

Acá se cimenta en código el principio 3 (contenido observado ≠ instrucciones)
y, en fases siguientes, la clasificación de reversibilidad (principio 4),
los permisos por agente y el registro de llm_calls (principio 8).
"""

from cortex.governance.injection import (
    TRUSTED_INSTRUCTION_SOURCES,
    ActionRecorder,
    is_trusted_instruction_source,
)

__all__ = [
    "TRUSTED_INSTRUCTION_SOURCES",
    "ActionRecorder",
    "is_trusted_instruction_source",
]
