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

import pytest

# Compiling a select needs every mapper configured, and the fulfilment models
# reference Order/Payment/Sku. Importing the API package registers them all;
# `test_player_check_service.py` carries the same line for the same reason.
import yupay.api.v1  # noqa: F401
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

            def first(self) -> object | None:
                return self._rows[0] if self._rows else None

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


async def test_a_young_order_is_checked_again_quickly() -> None:
    """The default delay is decided in SQL from the task's own age, so both
    cadences appear in the statement: fast while it is young, steady after.

    This is not only for the customer's sake. G-Engine's pay is two-phase —
    the tick that sees `verified` banks the intent and spends nothing, the
    *next* tick pays — so backing off to a minute right after the first check
    moves the delay from the news to the money. CI caught exactly that.
    """
    session = _Session()

    await ff.schedule_next_check(session, task_id="t1")  # type: ignore[arg-type]

    sql = _stmt_sql(session.statements[0])
    assert f"interval '{ff.FAST_RECHECK_SECONDS} seconds'" in sql
    assert f"interval '{ff.RECHECK_AFTER_SECONDS} seconds'" in sql
    assert "CASE" in sql.upper()


async def test_a_caller_may_pin_the_wait() -> None:
    """An explicit `seconds` skips the age test entirely — one interval, no
    branch."""
    session = _Session()

    await ff.schedule_next_check(session, task_id="t1", seconds=5)  # type: ignore[arg-type]

    sql = _stmt_sql(session.statements[0])
    assert "interval '5 seconds'" in sql
    assert "CASE" not in sql.upper()


async def test_the_fingerprint_covers_what_a_check_can_advance() -> None:
    """Status and metadata, because those are what "it got somewhere" means:
    a task that reached a terminal state, or one that banked a decision the
    next tick will act on."""
    session = _Session()

    await ff.task_progress_mark(session, task_id="t1")  # type: ignore[arg-type]

    sql = _stmt_sql(session.statements[0])
    assert "fulfillment_tasks.status" in sql
    assert "fulfillment_tasks.metadata" in sql
    # `updated_at` moves whenever an attempt row is written, including on a
    # check that learned nothing — keying on it would defer nothing, ever.
    assert "updated_at" not in sql
