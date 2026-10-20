"""DB errors must not carry bound parameters into log lines.

``str(DBAPIError)`` appends ``[parameters: ...]`` unless the engine hides
them, and many handlers log ``error=str(exc)`` — a key the redactor leaves
alone — so an email or Telegram id in a query reached Loki whenever the
database hiccupped.
"""

from __future__ import annotations

import pytest
from yupay.core import db as core_db


def test_engine_hides_bound_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_db, "_engine", None)
    engine = core_db.get_engine()
    try:
        assert engine.sync_engine.hide_parameters is True
    finally:
        monkeypatch.setattr(core_db, "_engine", None)
