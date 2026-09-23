"""Where an FX lookup gets its database session.

``load_override`` and ``load_chain`` are called from two very different
places: a request handler that is already holding a session, and a scheduler
tick that holds none. Both used to open their own session from the factory,
which is correct for the scheduler and a trap in a request.

The trap is pool amplification. A handler holds its session for its whole
lifetime, so opening a second one *while* the first is held makes every such
request cost two connections out of the same pool of ten plus ten. Effective
capacity halves, and it halves exactly when load is highest, because that is
when Redis misses and the DB path runs at all.

It cost us a production incident: on 2026-09-22 at 22:58 UTC the web
container's ISR windows lined up and it asked for every brand page at once.
Twenty-four of those requests died on
``QueuePool limit of size 10 overflow 10 reached`` inside
``catalog.routes.get_brand`` — each of them holding one connection and
waiting thirty seconds for a second.

So a caller that already has a session lends it, and only a caller that has
none opens one.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@contextlib.asynccontextmanager
async def fx_session(
    *,
    db: AsyncSession | None,
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> AsyncIterator[AsyncSession | None]:
    """Yield a session to read FX settings with, or ``None`` when there is none.

    A lent ``db`` is yielded as-is and **never closed** — it belongs to the
    caller's request and closing it here would break everything after this
    lookup. A factory-built one is closed on exit, as before.
    """
    if db is not None:
        yield db
        return
    if session_factory is None:
        yield None
        return
    async with session_factory() as owned:
        yield owned
