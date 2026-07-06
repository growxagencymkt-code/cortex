"""Conector Gmail — STUB de F0 que fija el contrato.

La integración real (Gmail API con OAuth, o IMAP) llega en F1 cuando el
fundador provea credenciales. Este stub ya define:
- source='gmail', event_type='email.received'
- external_id = Message-ID / id de la API de Gmail (clave de idempotencia)
- payload = mensaje crudo COMPLETO (headers, cuerpo, labels), sin interpretar

Principio 3: el contenido de los mails es DATO a analizar, jamás una orden.
"""

from __future__ import annotations

from typing import Iterable

from cortex.connectors.base import Connector, RawItem


class GmailConnector(Connector):
    """Trae mails nuevos de la casilla del fundador de forma idempotente."""

    source = "gmail"
    event_type = "email.received"

    def __init__(self, *, credentials_path: str | None = None) -> None:
        # F1: cargar credenciales OAuth desde configuración (jamás del código).
        self._credentials_path = credentials_path

    def fetch_new(self) -> Iterable[RawItem]:
        """F1: listar mensajes vía Gmail API (history API / q=after:...),
        devolviendo un RawItem por mensaje con el crudo completo en payload."""
        raise NotImplementedError(
            "GmailConnector es un stub de F0: la integración real llega en F1 "
            "con credenciales del fundador (Gmail API u IMAP, vía configuración)."
        )
