"""The status sweep stays under a vendor's published read ceiling.

FazerCards allows 120 status reads a minute; on 2026-11-17 one buyer's burst
of fresh lines (each read every 10 s at first) drew 429s.
"""

from __future__ import annotations

from typing import Any

import pytest
from yupay_scheduler.jobs import panel_reconcile

pytestmark = pytest.mark.asyncio


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_a: object) -> None:
        return None


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _due(_session: Any, **kwargs: Any) -> list[str]:
        calls.append(kwargs)
        return []

    monkeypatch.setattr(panel_reconcile, "get_session_factory", lambda: _Session)
    monkeypatch.setattr(panel_reconcile, "due_reconcile_task_ids", _due)
    return calls


async def test_fzr_reads_at_most_its_budget_a_tick(asked: list[dict[str, Any]]) -> None:
    await panel_reconcile._list_due_task_ids("fzr")

    assert asked == [{"supplier": "fzr", "limit": panel_reconcile.PER_TICK["fzr"]}]
    per_minute = panel_reconcile.PER_TICK["fzr"] * 60 // panel_reconcile.INTERVAL_SECONDS
    assert per_minute < 120


async def test_a_vendor_without_a_ceiling_keeps_the_default(asked: list[dict[str, Any]]) -> None:
    await panel_reconcile._list_due_task_ids("nova")

    assert asked == [{"supplier": "nova"}]
