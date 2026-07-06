"""Tests de los comandos F2 `cortex ask` y `cortex digest` (memory, costo $0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortex.cli import main as cli_main

_FIXTURE = str(Path(__file__).parent / "fixtures" / "sample_emails.jsonl")


def test_cli_ask_grounded_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli_main(["ask", "fenix", "--store", "memory", "--fixture", _FIXTURE])
    out = capsys.readouterr().out
    assert code == 0
    assert "Consulta: fenix" in out
    assert "Fragmentos:" in out or "Hechos" in out


def test_cli_ask_unknown_says_dont_know(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli_main(["ask", "xkcd-qwerty-zzznope", "--store", "memory", "--fixture", _FIXTURE])
    out = capsys.readouterr().out
    assert code == 0
    assert "No sé" in out or "No se" in out


def test_cli_digest_lists_commitments(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli_main(["digest", "--store", "memory", "--fixture", _FIXTURE, "--days", "3650"])
    out = capsys.readouterr().out
    assert code == 0
    assert "compromisos que vencen" in out
    assert "[evento" in out  # al menos un compromiso con evidencia


def test_cli_ask_missing_fixture_errors() -> None:
    assert cli_main(["ask", "x", "--store", "memory", "--fixture", "no/existe.jsonl"]) == 2
