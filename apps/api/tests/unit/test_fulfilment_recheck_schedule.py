"""When the next status check is due.

Both reconcilers used to sweep every in-flight task every 60 seconds, which
is the wrong shape for work that often finishes in seconds. NOVA delivered a
Telegram Stars order within seconds on 2026-09-20 and the customer watched
"в обработке" until the minute was up; G-Engine is worse, because its
two-phase pay means the *payment* waits for the next tick, not just the news
of it.

The fix leans on a column that already existed and nobody wrote:
`next_attempt_at` unset means "nobody has asked yet", which is exactly what a
fresh order carries. So the sweep can tick every ten seconds and still not
poll an order it asked about nine seconds ago.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

# Compiling a select needs every mapper configured, and the fulfilment models
# reference Order/Payment/Sku. Importing the API package registers them all;
# `test_player_check_service.py` carries the same line for the same reason.
import yupay.api.v1  # noqa: F401
from yupay.core.clock import now
from yupay.modules.fulfillment import service as ff

pytestmark = pytest.mark.asyncio


def _stmt_sql(stmt: object) -> str:
    return str(stmt).replace("\n", " ")


class _Session:
    """Captures the statement instead of running it."""

    def __init__(self, rows: list[str] | None = None) -> None:
        self.rows = rows or []
        self.statements: list[object] = []

    async def execute(self, stmt: object) -> object:
        self.statements.append(stmt)

        class _R:
            def __init__(self, rows: list[str]) -> None:
                self._rows = rows

            def scalars(self) -> _R:
                return self

            def all(self) -> list[str]:
                return self._rows

        return _R(self.rows)


async def test_a_task_nobody_has_asked_about_is_due() -> None:
    """`next_attempt_at IS NULL` has to be part of the predicate, or a fresh
    order is never picked up at all and the sweep goes silent."""
    session = _Session(["t1"])

    ids = await ff.due_reconcile_task_ids(session, supplier="nova")  # type: ignore[arg-type]

    sql = _stmt_sql(session.statements[0])
    assert "next_attempt_at IS NULL" in sql
    assert ids == ["t1"]


async def test_the_query_is_scoped_to_one_supplier_and_in_flight_work() -> None:
    session = _Session()

    await ff.due_reconcile_task_ids(session, supplier="gengine")  # type: ignore[arg-type]

    sql = _stmt_sql(session.statements[0])
    assert "fulfillment_tasks.supplier" in sql
    assert "fulfillment_tasks.status" in sql


async def test_the_next_check_is_pushed_out_by_the_steady_cadence() -> None:
    session = _Session()
    before = now()

    await ff.schedule_next_check(session, task_id="t1")  # type: ignore[arg-type]

    stmt = session.statements[0]
    scheduled = stmt.compile().params["next_attempt_at"]  # type: ignore[attr-defined]
    delta = scheduled - before
    assert timedelta(seconds=ff.RECHECK_AFTER_SECONDS - 2) <= delta
    assert delta <= timedelta(seconds=ff.RECHECK_AFTER_SECONDS + 2)


async def test_a_caller_may_ask_for_a_shorter_wait() -> None:
    """The knob exists so a supplier that answers fast can be asked again
    sooner without changing the default for everyone."""
    session = _Session()
    before = now()

    await ff.schedule_next_check(session, task_id="t1", seconds=5)  # type: ignore[arg-type]

    scheduled = session.statements[0].compile().params["next_attempt_at"]  # type: ignore[attr-defined]
    assert scheduled - before <= timedelta(seconds=7)
