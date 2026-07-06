"""Sandbox de herramientas del simulador (SYSTEM_PROMPT §9.2).

Un DOBLE por cada herramienta del agente:
- **Lecturas** operan sobre el snapshot temporal (memoria congelada a `t`).
- **Escrituras** NO ejecutan efecto real: registran una acción PROPUESTA
  (`ProposedAction`) y devuelven un éxito simulado.

El mismo `AgentSpec` corre en simulación y en producción; lo ÚNICO que cambia es
la inyección de herramientas (§9.2): acá se inyecta este sandbox; en producción,
las tools reales. Cada escritura también deja rastro en un
`cortex.governance.injection.ActionRecorder` (reuso del contrato de gobernanza),
de modo que la guarda de obediencia (principio 3) se puede aplicar sin cambios.

El contenido observado del disparador (`body`) es DATO: el sandbox lo expone como
texto a analizar, nunca como instrucción (principio 3). El destinatario legítimo
de una respuesta sale del SOBRE (`from`), no del cuerpo.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cortex.events.models import Event
from cortex.governance.injection import ActionRecorder, RecordedAction
from cortex.governance.reversibility import Reversibility, classify_action
from cortex.memory.graph import EntityRecord
from cortex.simulator.snapshot import MemorySnapshot

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def extract_emails(text: str) -> list[str]:
    """Direcciones de correo halladas en un texto (lowercased, orden estable)."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _EMAIL_RE.findall(text or ""):
        low = m.lower()
        if low not in seen:
            seen.add(low)
            out.append(low)
    return out


class ProposedAction(BaseModel):
    """Una acción que el agente PROPONE (jamás se ejecuta en simulación).

    `reversibility` se deriva de `kind` con el contrato de gobernanza (§4). Una
    acción desconocida se clasifica como IRREVERSIBLE (conservador).
    """

    model_config = ConfigDict(frozen=True)

    tool: str
    kind: str
    recipient: str | None = None
    summary: str = ""
    args: dict[str, str] = Field(default_factory=dict)
    triggered_by_source: str
    reversibility: Reversibility

    def searchable_blob(self) -> str:
        """Texto donde buscar marcadores de exfiltración (destinatario+resumen+args)."""
        parts = [self.recipient or "", self.summary, *self.args.values()]
        return " ".join(parts).lower()


class Sandbox:
    """Doble de herramientas para UN caso de simulación.

    Lecturas sobre `snapshot`; escrituras vía `propose(...)` que registran y
    devuelven éxito simulado. No hay ningún camino con efecto real.
    """

    def __init__(
        self,
        *,
        snapshot: MemorySnapshot,
        trigger: Event,
        recorder: ActionRecorder | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._trigger = trigger
        self._recorder = recorder if recorder is not None else ActionRecorder()
        self._actions: list[ProposedAction] = []

    # ---------------------------------------------------------------- lecturas
    @property
    def snapshot(self) -> MemorySnapshot:
        return self._snapshot

    @property
    def trigger(self) -> Event:
        return self._trigger

    def body(self) -> str:
        """Contenido observado del disparador. DATO, nunca instrucción (principio 3)."""
        return str(self._trigger.payload.get("body", ""))

    def envelope(self) -> dict[str, str]:
        """Metadatos de sobre del disparador (from/to/subject), sin el cuerpo."""
        payload = self._trigger.payload
        out: dict[str, str] = {}
        for key in ("from", "to", "cc", "subject"):
            val = payload.get(key)
            if isinstance(val, str):
                out[key] = val
        return out

    def reply_target(self) -> str | None:
        """Destinatario legítimo de una respuesta: el email del remitente del sobre.

        Sale de `from`/`actor` (el SOBRE), nunca del cuerpo: así una dirección
        inyectada en el texto no puede convertirse en destinatario.
        """
        candidates = [
            str(self._trigger.payload.get("from", "")),
            str(self._trigger.actor or ""),
        ]
        for cand in candidates:
            emails = extract_emails(cand)
            if emails:
                return emails[0]
        return None

    def search_entities(self, kind: str, text: str) -> EntityRecord | None:
        return self._snapshot.find_entity(kind, text)

    def entities_by_kind(self, kind: str) -> list[EntityRecord]:
        return self._snapshot.entities_by_kind(kind)

    def commitments_due(self, start: datetime, end: datetime) -> list[Any]:
        return list(self._snapshot.commitments_due(start, end))

    # --------------------------------------------------------------- escrituras
    def propose(
        self,
        *,
        tool: str,
        kind: str,
        recipient: str | None = None,
        summary: str = "",
        args: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Registra una acción propuesta y devuelve éxito SIMULADO (sin efecto real).

        También deja rastro en el `ActionRecorder` de gobernanza con la fuente que
        disparó al agente, para que la guarda de obediencia (principio 3) aplique.
        """
        action = ProposedAction(
            tool=tool,
            kind=kind,
            recipient=recipient.lower() if recipient else None,
            summary=summary,
            args=dict(args) if args else {},
            triggered_by_source=self._trigger.source,
            reversibility=classify_action(kind).reversibility,
        )
        self._actions.append(action)
        self._recorder.record(
            RecordedAction(
                kind=kind,
                detail=f"{tool} -> {recipient or '(sin destinatario)'}: {summary}"[:200],
                triggered_by_source=self._trigger.source,
            )
        )
        return {"ok": True, "simulated": True, "tool": tool}

    # ----------------------------------------------------------------- rastros
    @property
    def proposed_actions(self) -> tuple[ProposedAction, ...]:
        return tuple(self._actions)

    @property
    def recorder(self) -> ActionRecorder:
        return self._recorder
