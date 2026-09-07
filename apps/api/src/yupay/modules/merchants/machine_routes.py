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
``RuntimeError("Stream consumed")``. Four of the five endpoints here are GETs
and the fifth takes a JSON body, so the rule binds today and as this router
grows.

## No ``Idempotency-Key`` anywhere on this router

AGENTS.md §9 requires the header on state-changing endpoints. ``/me`` and
``/catalog`` are reads, so it does not reach them. ``POST /orders`` *is* a
mutation and still does not take it: it is idempotent on the merchant's own
``merchant_order_id`` instead (spec §9.3), which is stronger here rather than
weaker. A header key is minted per attempt by our client; ``merchant_order_id``
is minted per *intent* by theirs, is the id their own system already keys on,
and is what a replayed request necessarily carries — and a signature on this
API is deliberately not single-use (see ``auth.py``), so endpoint idempotency
is the only thing that makes a replayed mutation harmless. Accepting a second,
weaker key beside it would only give an integrator two ways to be idempotent
and one of them wrong. AGENTS.md §9 records the exception.

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

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.modules.merchants import api as merchants
from yupay.modules.merchants.auth import merchant_auth
from yupay.modules.merchants.machine_schemas import (
    MerchantCatalogOut,
    MerchantOrderCreateIn,
    MerchantOrderOut,
    MerchantOrderStatusOut,
    MerchantProfileOut,
    MerchantTransactionsOut,
)
from yupay.modules.merchants.models import Merchant

#: Ledger page bounds. The ceiling matches the admin ledger route's, so there
#: is one number in the repo for "how many deposit rows in one page", and
#: out-of-range is a 422 rather than a silent clamp — a client that asked for
#: 500 and got 200 has no way to tell.
TRANSACTIONS_PAGE_MAX = 200
TRANSACTIONS_PAGE_DEFAULT = 50

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


@router.post(
    "/orders",
    response_model=MerchantOrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Place an order and settle it from the deposit",
)
async def place_order(
    body: MerchantOrderCreateIn, merchant: AuthedMerchant, db: Db
) -> MerchantOrderOut:
    """Buy one SKU against the prepaid deposit.

    The whole flow — pricing, the ±2% drift rule, the margin floor, the
    deposit debit, ``paid`` and the start of fulfilment — is
    ``merchants.orders.place``'s; this parses and dispatches. Idempotent on
    ``merchant_order_id``: the same id with the same body returns the order
    already placed, a different body is a ``409``.
    """
    return await merchants.place_order(db, merchant=merchant, body=body)


@router.get(
    # ``:path``, not a plain ``{merchant_order_id}``. ``merchant_order_id`` is
    # ``^[\x21-\x7e]+$``, which includes ``/`` (0x2F) — the auth README's own
    # worked example is ``/merchant/v1/orders/my%2Forder`` — and Starlette's
    # default ``str`` convertor compiles to ``[^/]+``, so the decoded segment
    # ``my/order`` would not match the route at all and every such order would
    # 404. The convertor changes nothing else: FastAPI's ``path_format`` still
    # renders ``{merchant_order_id}`` in the OpenAPI schema, and what the
    # signature covers is the raw request line either way (``auth.request_target``).
    #
    # **It is greedy, and it shadows the whole subtree.** ``:path`` compiles to
    # ``.*``, so ``/merchant/v1/orders/a/b/c/d`` matches here and answers
    # ``order_not_found``. Harmless today because nothing else lives under
    # ``/orders/``, but a future ``/orders/{id}/deliveries`` or
    # ``/orders/{id}/refund`` (M3) registered **after** this route would be
    # silently swallowed rather than routed — Starlette takes the first full
    # match in declaration order. Register any such route **above** this one,
    # and note that its own ``{id}`` would then need the same convertor for the
    # same reason. The module README's file map says so too.
    "/orders/{merchant_order_id:path}",
    response_model=MerchantOrderStatusOut,
    summary="Read one of your orders back, with its delivered code",
)
async def read_order(
    merchant: AuthedMerchant,
    db: Db,
    merchant_order_id: Annotated[
        str,
        Path(description="Your own id for the order, percent-encoded in the path."),
    ],
) -> MerchantOrderStatusOut:
    """Return one order's status, timeline, delivered artifact and refund mark.

    Scoped to the authenticated merchant and to their own id — see
    ``merchants.order_status``, which also explains why an order belonging to
    another merchant answers with the same 404 as one that never existed.

    The path segment arrives percent-decoded, so an id containing ``/``
    (legal, and in the README's worked example) is matched against the stored
    value rather than split into route segments.
    """
    return await merchants.read_order_status(
        db, merchant=merchant, merchant_order_id=merchant_order_id
    )


@router.get(
    "/transactions",
    response_model=MerchantTransactionsOut,
    summary="Your deposit ledger, newest first",
)
async def read_transactions(
    merchant: AuthedMerchant,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=TRANSACTIONS_PAGE_MAX)] = TRANSACTIONS_PAGE_DEFAULT,
    cursor: Annotated[str | None, Query()] = None,
) -> MerchantTransactionsOut:
    """Return one page of the calling merchant's deposit movements.

    Paging, the shared grouped query and why it is keyset rather than OFFSET
    are all ``merchants.transactions``'. The merchant comes from the signature;
    no parameter here names one.

    Note that ``limit`` and ``cursor`` are part of the signed canonical string
    (Task 2's fourth field, the raw query), so a signature does not carry
    across a change of page.
    """
    return await merchants.build_transactions_page(
        db, merchant_id=merchant.id, limit=limit, cursor=cursor
    )


__all__ = ["router"]
