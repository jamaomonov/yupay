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

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from yupay.core.config import Settings


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
        integrations=extras,
    )


__all__ = ["init_sentry"]
