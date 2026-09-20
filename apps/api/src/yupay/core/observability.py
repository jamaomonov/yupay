"""Error reporting, for every service that has a `Settings` and a process.

`init_sentry` lived in `bootstrap.py` until 2026-09-09, which meant only the
API ever called it. The worker, the scheduler and the bot all load the same
`api.env` and therefore held the DSN, and all three reported nothing — so a
crash in the fulfilment drain, the refund seam or the webhook delivery went
only to the container log. That is the half of the system where money moves.

It could not simply be imported from there: `bootstrap` imports
`yupay.api.v1` at module scope, so a worker reaching for `_init_sentry` would
drag the entire `/api/v1` route stack into a process that serves no HTTP. This
module has no such dependency, which is the whole reason it exists.

The two PII switches are the load-bearing part and are explained at the call.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sentry_sdk.types import Breadcrumb, BreadcrumbHint, Event, Hint

    from yupay.core.config import Settings

#: A Telegram bot token as it appears inside an API URL:
#: ``https://api.telegram.org/bot<numeric id>:<secret>/sendMessage``.
#:
#: The secret half is what this matches. Anchored on ``/bot<digits>:`` so it
#: cannot fire on ordinary text — the numeric id, the colon and the ``/bot``
#: prefix together are specific to this one shape.
_TELEGRAM_TOKEN_IN_URL = re.compile(r"(/bot\d+:)[A-Za-z0-9_-]{20,}")

_REDACTED = "[redacted]"


def _scrub(value: str) -> str:
    """Replace a Telegram bot token inside a URL with a placeholder."""
    return _TELEGRAM_TOKEN_IN_URL.sub(rf"\1{_REDACTED}", value)


def _scrub_deep(value: Any) -> Any:
    """Walk strings, lists and dicts, scrubbing every string it reaches.

    Deep rather than "check the two keys we expect": the SDK puts the URL in
    ``breadcrumb["data"]["url"]``, the stdlib-logging integration puts the
    same text in ``breadcrumb["message"]``, and an exception raised by an HTTP
    client can carry it in its own message. A scrubber that knew only the
    first would have left the other two shipping the token, which is exactly
    the shape that made this necessary.
    """
    if isinstance(value, str):
        return _scrub(value)
    if isinstance(value, list):
        return [_scrub_deep(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub_deep(v) for k, v in value.items()}
    return value


def _before_breadcrumb(crumb: Breadcrumb, _hint: BreadcrumbHint) -> Breadcrumb:
    """Strip Telegram bot tokens out of every breadcrumb before it is sent."""
    return _scrub_deep(crumb)  # type: ignore[no-any-return]


def _before_send(event: Event, _hint: Hint) -> Event:
    """The same, for the event itself — message, exception values, request."""
    return _scrub_deep(event)  # type: ignore[no-any-return]


def init_sentry(settings: Settings, *, integrations: str = "asgi") -> None:
    """Initialise Sentry if a DSN is configured, otherwise do nothing.

    The SDK is imported inside the function, not at module scope, so a dev
    environment without a DSN does not pay ~2 MB of import for a no-op.

    Args:
        settings: The app settings. `sentry_dsn` empty or unset is the
            supported "reporting is off" state and returns immediately.
        integrations: `"asgi"` adds the FastAPI/Starlette integrations, which
            attribute an event to the endpoint that raised it. Any other value
            registers none — right for the worker, the scheduler and the bot,
            which serve no requests and where those integrations would find
            nothing to hook. The transaction is then the service name, which is
            what `release` already carries.

    Returns:
        None. Failing to configure reporting must never stop a service from
        starting: a process that refuses to run because it cannot phone home
        is a worse outcome than one running unobserved.
    """
    if not settings.sentry_dsn:
        return

    import sentry_sdk

    extras = []
    if integrations == "asgi":
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        extras = [
            FastApiIntegration(transaction_style="endpoint"),
            StarletteIntegration(transaction_style="endpoint"),
        ]

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.service_name,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # TWO switches, and each covers a different half. ``send_default_pii``
        # governs request bodies, headers, cookies and user identity;
        # ``include_local_variables`` governs the **stack-frame locals**
        # attached to every exception event and defaults to ``True``. With
        # only the first set, any 500 raised while a secret is a live local —
        # a freshly minted merchant API key or webhook signing secret, both of
        # which exist in the clear in exactly one frame — ships that secret to
        # a third-party SaaS. AGENTS.md §9.
        #
        # Verified on prod 2026-09-09, event 80e82e4423c347828473bf82fe00352c:
        # the frame carries no ``vars`` key. See docs/runbooks/first-deploy.md.
        send_default_pii=False,
        include_local_variables=False,
        # A THIRD leak the two switches above do not cover. aiogram talks to
        # ``https://api.telegram.org/bot<token>/<method>``, and the SDK records
        # every outgoing request as a breadcrumb **with its URL** — so the bot
        # token, which is full control of the bot, was riding along on every
        # event the bot reported. Neither ``send_default_pii`` nor
        # ``include_local_variables`` touches a breadcrumb.
        #
        # Found 2026-09-21 in a real bot event, where the token was legible in
        # the httplib breadcrumbs beside the stack trace.
        before_breadcrumb=_before_breadcrumb,
        before_send=_before_send,
        integrations=extras,
    )


__all__ = ["init_sentry"]
