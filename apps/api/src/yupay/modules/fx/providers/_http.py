"""Shared HTTP-client context helper for FX provider adapters.

Each provider may either be given a long-lived :class:`httpx.AsyncClient` (good for tests
and shared connection pools) or transparently create + dispose a transient one. This
helper hides the branch behind a typed ``AbstractAsyncContextManager``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx


@asynccontextmanager
async def client_context(shared: httpx.AsyncClient | None) -> AsyncIterator[httpx.AsyncClient]:
    """Yield ``shared`` if provided, else a transient :class:`httpx.AsyncClient`."""
    if shared is not None:
        yield shared
        return
    async with httpx.AsyncClient() as transient:
        yield transient
