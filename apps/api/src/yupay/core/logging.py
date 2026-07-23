"""Structured logging via structlog.

In production we emit JSON; in development we emit human-readable key-value.
Sensitive fields are blocklisted by the redactor.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from yupay.core.config import get_settings

REDACTED_KEYS = frozenset(
    {
        "email",
        "phone",
        "password",
        "token",
        "access_token",
        "refresh_token",
        "guest_token",
        "ip",
        "user_agent",
        "telegram_id",
        "tg_user_id",
        "voucher_code",
        "code",
        "api_key",
        "authorization",
        "stripe-signature",
        "octo_secret",
        "octo_signature_key",
        "payme_key",
        "payme_test_key",
        "uzum_password",
        "uzum_test_password",
        "click_secret_key_web",
        "click_secret_key_bot",
        "bearer_token",
        "merchant_token",
    },
)


def _redact_pii(
    _logger: Any,
    _name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Replace values for any blocklisted key with ``"<redacted>"``."""
    for key in list(event_dict):
        if key.lower() in REDACTED_KEYS:
            event_dict[key] = "<redacted>"
    return event_dict


def configure_logging() -> None:
    """Configure the standard library + structlog. Idempotent."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    # Silence third-party request loggers that log the full URL at INFO. httpx
    # in particular writes ``GET https://host/path?api=<key>`` — the Waxpeer
    # supplier passes its API key as a query param, so its key would land in the
    # logs (and Loki) verbatim. Our own structured ``*.request`` logs redact to
    # path-only; the stdlib redactor (``_redact_pii``) only covers structlog
    # events, not these. Cap them at WARNING so a real transport error still
    # surfaces without leaking credentials on every call.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _redact_pii,
    ]

    if settings.log_json:
        processors.append(structlog.processors.dict_tracebacks)
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger.

    Typed as ``Any`` because structlog's actual return type depends on the processor
    chain and is not statically known.
    """
    return structlog.get_logger(name)
