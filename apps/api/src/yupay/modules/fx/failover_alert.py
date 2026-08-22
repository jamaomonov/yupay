"""Page ops when the FX chain steps off the primary (or the next fallback).

Deduped in Redis so a 5-minute refresh while still on the same fallback does
not re-page. A further step (fallback A → fallback B, or all-dead → stale)
is a new fingerprint and alerts again.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from redis.asyncio import Redis

from yupay.core.logging import get_logger
from yupay.modules.fx.provider_chain import CATALOG_BY_SLUG, provider_slug
from yupay.modules.fx.providers.base import FxProvider
from yupay.modules.notifications.alerts import send_admin_alert

KIND = "fx_failover"
log = get_logger("yupay.fx.failover_alert")


def _key(base: str, quote: str) -> str:
    return f"fx:failover:{base.upper()}:{quote.upper()}"


def provider_label(provider: FxProvider) -> str:
    """Human name for the ops chat."""
    spec = CATALOG_BY_SLUG.get(provider_slug(provider))
    if spec is not None:
        return spec.title
    return provider.name


def format_failover_alert(
    *,
    base: str,
    quote: str,
    failed: Sequence[str],
    winner: str | None,
    stale: bool,
) -> str:
    pair = f"{base.upper()}→{quote.upper()}"
    failed_line = ", ".join(failed)
    if stale:
        src = winner or "кэш"
        return (
            f"<b>FX: все провайдеры молчат</b>\n"
            f"{pair}: отдаём stale ({src})\n"
            f"Не ответили: {failed_line}"
        )
    if winner is None:
        return (
            f"<b>FX: курс недоступен</b>\n"
            f"{pair}: ни один провайдер не ответил\n"
            f"Не ответили: {failed_line}"
        )
    return (
        f"<b>FX: сменили источник</b>\n{pair}: {failed[-1]} → {winner}\nНе ответили: {failed_line}"
    )


async def notify_failover(
    redis: Redis,
    *,
    base: str,
    quote: str,
    failed: Sequence[str],
    winner: str | None,
    stale: bool = False,
) -> None:
    """Alert if this (failed, winner, stale) tuple is new for the pair.

    ``failed`` empty means the primary answered: clear the fingerprint so the
    next real failover pages again. Never raises.
    """
    key = _key(base, quote)
    try:
        if not failed:
            await redis.delete(key)
            return
        fingerprint = json.dumps(
            {"failed": list(failed), "winner": winner, "stale": stale},
            sort_keys=True,
        )
        previous = await redis.get(key)
        if previous == fingerprint:
            return
        await redis.set(key, fingerprint)
    except Exception:
        log.exception("fx.failover_alert.redis_failed", base=base, quote=quote)
        if not failed:
            return
    text = format_failover_alert(base=base, quote=quote, failed=failed, winner=winner, stale=stale)
    await send_admin_alert(text, kind=KIND)
