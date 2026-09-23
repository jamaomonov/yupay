"""A request handler must not take a second connection to read FX settings.

On 2026-09-22 at 22:58 UTC the web container's ISR windows lined up and it
asked the API for every brand page at once. Twenty-four of those died inside
``catalog.routes.get_brand`` on ``QueuePool limit of size 10 overflow 10
reached, connection timed out, timeout 30.00``.

The pool was not undersized for the traffic — it was undersized for the
*amplification*. A handler holds its session for its whole lifetime, and
``load_override`` opened a second one from the same pool while the first was
still held, so every brand page that missed the Redis cache cost two of the
twenty connections instead of one. Ten concurrent pages exhausted it, and each
of them then waited the full thirty seconds before failing.

What is pinned here is the property, not the incident: a caller that has a
session lends it, a caller that has none still opens one, and a lent session
is never closed by the borrower.
"""

from __future__ import annotations

from typing import Any

import pytest
from yupay.modules.fx.session_source import fx_session

pytestmark = pytest.mark.asyncio


class _Session:
    """Stands in for the handler's session. Records being closed."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:  # pragma: no cover - failure would show as closed
        self.closed = True

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.closed = True


class _Factory:
    """A session factory that counts how often it was asked for a connection."""

    def __init__(self) -> None:
        self.calls = 0
        self.made: list[_Session] = []

    def __call__(self) -> _Session:
        self.calls += 1
        session = _Session()
        self.made.append(session)
        return session


async def test_a_lent_session_is_used_and_the_pool_is_left_alone() -> None:
    """The fix, in one assertion: no second connection is taken."""
    lent: Any = _Session()
    factory = _Factory()

    async with fx_session(db=lent, session_factory=_as_factory(factory)) as session:
        borrowed: Any = session

    assert borrowed is lent
    assert factory.calls == 0, "a second connection was taken while the first was held"


async def test_a_lent_session_outlives_the_lookup() -> None:
    """Closing it would break every query the handler still has to run — the
    borrower reads and hands it back, it does not own it."""
    lent = _Session()

    async with fx_session(db=_as_session(lent), session_factory=None):
        pass

    assert lent.closed is False, "the borrower closed a session it does not own"


async def test_a_caller_without_a_session_still_gets_one() -> None:
    """The scheduler holds no session and must keep opening its own, closed on
    the way out exactly as before."""
    factory = _Factory()

    async with fx_session(db=None, session_factory=_as_factory(factory)) as session:
        opened: Any = session

    assert opened is factory.made[0]
    assert factory.calls == 1
    assert factory.made[0].closed is True


async def test_no_session_and_no_factory_is_not_an_error() -> None:
    """``None`` means "there is no database here" — the caller falls back to
    Redis or to its defaults rather than raising."""
    async with fx_session(db=None, session_factory=None) as session:
        assert session is None


def _as_factory(factory: _Factory) -> Any:
    """The real parameter is an ``async_sessionmaker``; the fake only needs to
    be callable, and typing it as such would be a lie either way."""
    return factory


def _as_session(session: _Session) -> Any:
    """Same, for the lent session. What is under test is that the object comes
    back untouched — making the fake a real ``AsyncSession`` would need a live
    engine and would test SQLAlchemy rather than this."""
    return session
