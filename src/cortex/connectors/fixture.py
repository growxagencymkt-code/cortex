"""Conector de fixtures — ingesta idempotente desde un corpus local (JSONL).

Sirve para dos cosas mientras no hay credenciales de Gmail (bloqueo F0):
1. Cerrar la forma de la aceptación F0 ("re-correr la ingesta no duplica",
   "meses de mails en events", "rebuild en verde") contra un corpus realista y
   DETERMINISTA, sin tocar la casilla real del fundador.
2. Cargar un export propio (p.ej. un volcado de mbox convertido a JSONL) sin
   depender de la API de Gmail.

Cada línea del JSONL es un mail: {external_id, ts (ISO), from, to, subject, body}.
El contenido es DATO (principio 3): este conector NO interpreta ni obedece nada,
sólo normaliza a RawItem. La idempotencia la garantiza la ingesta por
external_id, igual que con Gmail real.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from cortex.connectors.base import Connector, RawItem


class FixtureMailConnector(Connector):
    """Trae mails desde un archivo JSONL con el mismo contrato que GmailConnector."""

    source = "gmail"
    event_type = "email.received"

    def __init__(self, jsonl_path: str | Path) -> None:
        self._path = Path(jsonl_path)

    def fetch_new(self) -> Iterable[RawItem]:
        items: list[RawItem] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            record: dict[str, Any] = json.loads(line)
            payload = {
                "from": record.get("from", ""),
                "to": record.get("to", ""),
                "subject": record.get("subject", ""),
                "body": record.get("body", ""),
            }
            items.append(
                RawItem(
                    external_id=str(record["external_id"]),
                    ts=datetime.fromisoformat(record["ts"]),
                    actor=str(record.get("from", "")) or None,
                    payload=payload,
                )
            )
        return items
