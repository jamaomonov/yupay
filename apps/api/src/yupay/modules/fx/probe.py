"""Live-probe every FX adapter for the admin dashboard."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from yupay.modules.fx.provider_chain import (
    CATALOG_BY_SLUG,
    ChainItem,
    provider_configured,
    provider_slug,
)
from yupay.modules.fx.providers.base import FxProvider, FxProviderError
from yupay.modules.fx.schemas import ProviderChainItemOut, ProviderChainOut, ProviderQuoteOut


async def probe_chain(
    providers: Sequence[FxProvider],
    chain: Sequence[ChainItem],
    quotes: Sequence[str],
) -> ProviderChainOut:
    """Call each adapter for each quote in parallel. Failures become ``error``."""
    by_slug = {provider_slug(p): p for p in providers}
    first_primary: str | None = None
    items: list[ProviderChainItemOut] = []
    for item in chain:
        spec = CATALOG_BY_SLUG.get(item.slug)
        if spec is None:
            continue
        provider = by_slug.get(item.slug)
        configured = provider_configured(provider) if provider is not None else False
        if item.enabled and configured and first_primary is None:
            role = "primary"
            first_primary = item.slug
        elif not item.enabled:
            role = "off"
        elif not configured:
            role = "unconfigured"
        else:
            role = "fallback"
        quote_rows = (
            await asyncio.gather(*[_probe_one(provider, q) for q in quotes])
            if provider is not None
            else [ProviderQuoteOut(quote=q, rate=None, error="адаптер не собран") for q in quotes]
        )
        items.append(
            ProviderChainItemOut(
                slug=item.slug,
                title=spec.title,
                kind=spec.kind,
                enabled=item.enabled,
                configured=configured,
                role=role,
                sort_order=item.sort_order,
                quotes=list(quote_rows),
            )
        )
    return ProviderChainOut(quotes=list(quotes), items=items)


async def _probe_one(provider: FxProvider, quote: str) -> ProviderQuoteOut:
    if not provider.supports("USD", quote):
        return ProviderQuoteOut(quote=quote, rate=None, error="не обслуживает эту пару")
    try:
        q = await provider.get_rate("USD", quote)
    except FxProviderError as exc:
        return ProviderQuoteOut(quote=quote, rate=None, error=str(exc))
    return ProviderQuoteOut(quote=quote, rate=q.rate, error=None)
