"""The clock every figure in ``stats`` is bucketed on.

``date_trunc('day', <timestamptz>)`` truncates in the **session** timezone,
which is UTC on prod. That is five hours off the day an operator means, and it
does not announce itself: both numbers look plausible, and you only notice when
two views of the same data are put side by side.

The calendar did exactly that. A cell read $674.43 for 6 September; clicking it
showed $100.31, because the cell was a UTC day and the click asked for a
Tashkent one — on prod, that date held $674.43 across 23 orders in UTC and
$100.31 across 13 locally.

So the timezone lives here, in one place, imported by both halves rather than
redeclared in each. ``stats`` has no ``__init__`` imports, so this module is a
leaf: importing it cannot close a cycle back through ``service`` or
``analytics``, which is why it is not in ``analytics/_common.py``.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, func
from sqlalchemy.orm import InstrumentedAttribute

#: Uzbekistan, UTC+5. The business runs on one clock; there is no per-user
#: timezone anywhere in the admin, and inventing one here would only move the
#: disagreement rather than remove it.
LOCAL_TZ = "Asia/Tashkent"

#: The same zone for the Python side of a bucketed series — a zero-filled day
#: range has to be built from the same dates the query grouped by, or the fill
#: keys miss every bucket and the whole series reads as empty.
LOCAL_ZONE = ZoneInfo(LOCAL_TZ)


def local_day(column: InstrumentedAttribute[datetime | None]) -> ColumnElement[datetime]:
    """``column`` truncated to a day on the clock the business runs on."""
    return func.date_trunc("day", func.timezone(LOCAL_TZ, column))


def local_date_of(moment: datetime) -> str:
    """The ISO date ``moment`` falls on locally, as :func:`local_day` would key it."""
    return moment.astimezone(LOCAL_ZONE).date().isoformat()


__all__ = ["LOCAL_TZ", "LOCAL_ZONE", "local_date_of", "local_day"]
