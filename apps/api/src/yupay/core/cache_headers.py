"""``Cache-Control: no-store`` on every API response that does not set its own.

The API had no caching headers at all, which leaves the decision to whoever sits in
between: a browser may cache a GET heuristically, and a Cloudflare "cache everything"
rule would cache JSON. Order and trade progress, live offers and balances change by
the second, and a stale copy of any of them is a wrong answer shown to a customer.
So the default is "never store"; a route that genuinely wants caching sets its own
``Cache-Control`` and this middleware leaves it alone.

Pure ASGI (not ``BaseHTTPMiddleware``) so streamed bodies — CSV exports — pass
through untouched.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class NoStoreByDefault:
    """ASGI middleware adding ``Cache-Control: no-store`` when a response has none."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass through, stamping the header on the response start message."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def stamp(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "cache-control" not in headers:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, stamp)


__all__ = ["NoStoreByDefault"]
