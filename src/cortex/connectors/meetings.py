"""Conector de reuniones — transcripciones del Copiloto como eventos del log.

Dos modos de entrada, ambos idempotentes por `external_id`:
- en memoria: una lista de dicts de reunión (p.ej. traída de la API del Copiloto),
- desde disco: un JSONL exportado (una reunión por línea).

Complementa la vía en tiempo real (el Copiloto hace POST a `/api/ingest/meeting`):
este conector sirve para el **backfill** del histórico. El contenido es DATO
(principio 3): sólo se normaliza a evento; nada de lo transcripto se obedece.

Forma esperada de cada reunión (tolerante a las variantes del Copiloto):
  {id|external_id, user, title, platform, topic|topic_name, started_at (epoch),
   ended_at, duration_s, transcript, summary{...}, day}
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from cortex.connectors.base import Connector, RawItem


def _external_id(m: dict[str, Any]) -> str:
    ext = m.get("external_id")
    if ext:
        return str(ext)
    return f"copiloto-meeting-{m.get('user', '')}-{m.get('id', '')}"


def _ts(m: dict[str, Any]) -> datetime:
    started = m.get("started_at")
    if isinstance(started, (int, float)) and started > 0:
        return datetime.fromtimestamp(float(started), tz=UTC)
    if isinstance(started, str) and started:
        try:
            return datetime.fromisoformat(started)
        except ValueError:
            pass
    return datetime.now(tz=UTC)


def _payload(m: dict[str, Any]) -> dict[str, Any]:
    summary = m.get("summary")
    return {
        "external_id": _external_id(m),
        "user": str(m.get("user") or ""),
        "day": str(m.get("day") or ""),
        "title": str(m.get("title") or ""),
        "platform": str(m.get("platform") or ""),
        "topic": str(m.get("topic") or m.get("topic_name") or ""),
        "started_at": m.get("started_at"),
        "ended_at": m.get("ended_at"),
        "duration_s": m.get("duration_s") or 0,
        "transcript": str(m.get("transcript") or ""),
        "summary": summary if isinstance(summary, (dict, str)) else {},
    }


class MeetingsConnector(Connector):
    """Trae reuniones (de una lista o un JSONL) como eventos `meeting.transcript`."""

    source = "meetings"
    event_type = "meeting.transcript"

    def __init__(
        self,
        meetings: Iterable[dict[str, Any]] | None = None,
        *,
        jsonl_path: str | Path | None = None,
    ) -> None:
        self._meetings = list(meetings) if meetings is not None else None
        self._path = Path(jsonl_path) if jsonl_path is not None else None

    def _load(self) -> list[dict[str, Any]]:
        if self._meetings is not None:
            return self._meetings
        if self._path is not None:
            records: list[dict[str, Any]] = []
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict):
                    records.append(obj)
            return records
        return []

    def fetch_new(self) -> Iterable[RawItem]:
        items: list[RawItem] = []
        for m in self._load():
            payload = _payload(m)
            items.append(
                RawItem(
                    external_id=payload["external_id"],
                    ts=_ts(m),
                    actor=payload["user"] or None,
                    payload=payload,
                )
            )
        return items
