"""The machine API — ``/merchant/v1``, the surface a reseller's server calls.

Mounted by ``bootstrap`` at its **own** prefix, not under ``/api/v1``: this is
a third-party contract with its own versioning story (a breaking change means
``/merchant/v2``, never an edit), its own auth scheme, and its own error
vocabulary. Hanging it off the storefront's ``/api/v1`` would tie the two
versions together for no reason.

Every endpoint sits behind ``auth.merchant_auth`` — imported from ``auth``
directly, never through the ``merchants.api`` facade, which cannot re-export
it without closing an import cycle back through the v1 route stack. Business
logic is imported through the facade like everywhere else (AGENTS.md §6:
routers parse and dispatch).

**JSON bodies only.** The dependency reads ``await request.body()``; an
endpoint declaring ``Form(...)`` or ``UploadFile`` would send FastAPI down the
``request.form()`` branch, which consumes the stream without populating the
cache the dependency relies on, and every call to it would raise
``RuntimeError("Stream consumed")``. Both endpoints here are GETs, but the
constraint binds this router as it grows.

## No ``Idempotency-Key`` on these two

AGENTS.md §9 requires the header on state-changing endpoints. These are reads,
so it does not apply. Order creation (Task 4) is idempotent on the merchant's
own ``merchant_order_id`` rather than on the header — spec §9.3, and the
reason is in ``auth.py``: a signature is not single-use, so endpoint
idempotency is the only thing that makes a replayed mutation harmless.

## Rate limiting: this prefix is exempt from the coarse tier

Throttling here is the dependency's two Redis counters and nothing else: per
source IP on the ``merchant-api`` bucket, and per ``key_id`` once the
signature verifies, both 600/60 s, both answering RFC 7807 with a
``Retry-After``.

The app-wide slowapi limiter does **not** apply — ``bootstrap.
_exempt_self_authenticating_routes`` walks this router and exempts every
handler on it. That is a correction of an earlier reading, and the reasoning
is worth keeping because it is easy to get wrong twice. ``SlowAPIMiddleware``
matches every route on the app, not only ``/api/v1``'s, so the coarse tier
did cover this prefix. It was thought harmless because it buckets **per IP
per endpoint** while our IP guard is one counter for the whole prefix — true
whenever a caller's traffic spreads across endpoints, and false in exactly
the case that matters: with both tiers at 600/60 s, a caller concentrated on
one endpoint advances both counters at the same rate, ``limits`` allows
``count <= limit`` where ``ip_guard.hit_counter`` returns ``count > limit``,
and the middleware runs before any dependency — so they trip on the same
request and slowapi wins it. The README tells resellers to poll ``/catalog``
because there are no price webhooks, which is that case by design, and what
they would get is slowapi's handler body: no ``type``, no ``code``, not
problem+json, from an endpoint whose error contract we published.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.merchants import api as merchants
from yupay.modules.merchants.auth import merchant_auth
from yupay.modules.merchants.models import Merchant
from yupay.modules.merchants.schemas import MerchantCatalogOut, MerchantProfileOut

#: ``dependencies`` on the router rather than only on each handler: a route
#: added later without an ``AuthedMerchant`` parameter is still authenticated,
#: so forgetting the parameter costs a broken handler and not an open
#: endpoint. The handlers keep the parameter because they need the row;
#: FastAPI caches a sub-dependency within a request, so ``merchant_auth``
#: still runs exactly once. ``test_no_machine_endpoint_answers_an_unsigned_request``
#: sweeps the mounted app either way.
router = APIRouter(
    prefix="/merchant/v1",
    tags=["merchant-api"],
    dependencies=[Depends(merchant_auth)],
)

AuthedMerchant = Annotated[Merchant, Depends(merchant_auth)]
Db = Annotated[AsyncSession, Depends(db_session)]


@router.get(
    "/me",
    response_model=MerchantProfileOut,
    summary="The calling merchant's profile and live deposit balance",
)
async def read_me(merchant: AuthedMerchant, db: Db) -> MerchantProfileOut:
    """Return who is calling and what they can spend.

    ``balance_usd`` is the deposit ledger's signed posting sum, read live —
    there is no balance column, so nothing can drift from it. A merchant who
    has never been credited reads ``"0.00"``.
    """
    return MerchantProfileOut(
        merchant_id=merchant.id,
        title=merchant.title,
        status=merchant.status,
        balance_usd=await merchants.deposit_balance(db, merchant_id=merchant.id),
    )


@router.get(
    "/catalog",
    response_model=MerchantCatalogOut,
    summary="The wholesale price list, priced for the calling merchant",
)
async def read_catalog(merchant: AuthedMerchant, db: Db) -> MerchantCatalogOut:
    """Return every B2B-visible, priced SKU with this merchant's price.

    Visibility, pricing and the query shape are all
    ``price_list.build``'s — see that module. Every ``price_usd`` here is the
    price this merchant would be charged; SKUs without a cost are absent
    rather than free, and there are no price webhooks, so poll this and watch
    each SKU's ``updated_at`` (spec §8.4).
    """
    return await merchants.build_price_list(db, merchant=merchant)


__all__ = ["router"]
