"""HTTP surface for the merchant cabinet (spec §11).

A **BFF**, not a second machine API. The browser never holds a merchant's HMAC
secret — that credential belongs to their server — so the cabinet signs in with
a password, carries a short-lived ``merchant_access`` JWT, and this router does
the work on their behalf.

Every route takes the merchant from ``current_merchant_user``'s result and
never from a parameter: that is the single rule keeping one reseller out of
another's catalog, deposit and orders.

**Ordering here walks the machine API's path exactly** — ``quote``, the margin
floor, the deposit charge, the fulfilment enqueue — with a derived
``manual-<digest>`` standing in for the ``merchant_order_id`` a person should
not have to invent (spec §11). A cabinet order and an API order are therefore the
same kind of thing in history, in the ledger and in a dispute, which is what
lets the catalog page double as the no-code first purchase.

Unlike ``/merchant/v1`` this is **not** exempt from the coarse rate limit: that
exemption exists because a 429 to a signing acquirer costs money and buys
nothing (AGENTS.md §9). A password form is the opposite case, and the two
credential routes carry the two-axis ``ip_guard`` besides.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi import APIRouter, Response, status

from yupay.core.idempotency import normalize_idempotency_key
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.merchants import (
    cabinet_export,
    cabinet_notify,
    cabinet_orders,
    cabinet_summary,
    credentials,
    deposit,
    orders,
    price_list,
    transactions,
)
from yupay.modules.merchants.cabinet_deps import CurrentUser, Db, merchant_of
from yupay.modules.merchants.cabinet_schemas import (
    CabinetApiKeyCreateIn,
    CabinetApiKeyOut,
    CabinetIssuedKeyOut,
    CabinetOrderDetailOut,
    CabinetOrderIn,
    CabinetOrdersOut,
    CabinetProfileOut,
    CabinetProfilePatchIn,
    CabinetSummaryOut,
)
from yupay.modules.merchants.machine_schemas import (
    MerchantCatalogOut,
    MerchantOrderCreateIn,
    MerchantOrderOut,
    MerchantTransactionsOut,
)
from yupay.modules.merchants.route_replay import IdempotencyKeyHeader

log = get_logger("yupay.merchants.cabinet_routes")

router = APIRouter(prefix="/merchant/cabinet", tags=["merchant-cabinet"])


@router.get("/me", response_model=CabinetProfileOut, summary="The operator and their company")
async def me(user: CurrentUser, db: Db) -> CabinetProfileOut:
    merchant = await merchant_of(db, user)
    return CabinetProfileOut(
        user_id=user.id,
        email=user.email,
        timezone=user.timezone,
        merchant_id=merchant.id,
        title=merchant.title,
        status=merchant.status,
        balance_usd=await deposit.deposit_balance(db, merchant_id=merchant.id),
        offer_version=user.offer_version,
        offer_accepted_at=user.offer_accepted_at,
    )


@router.patch("/me", response_model=CabinetProfileOut, summary="Change display settings")
async def update_me(body: CabinetProfilePatchIn, user: CurrentUser, db: Db) -> CabinetProfileOut:
    """Today that is the timezone, and only the timezone.

    No ``Idempotency-Key``: this is a **last-writer-wins** field, so a replayed
    request lands on the value it already set. The rule in AGENTS §9 protects
    a write whose repetition is not the same as its first execution — a
    charge, a minted credential — and this one has no such shape. A future
    field on this endpoint that does needs the header and a line there.
    """
    user.timezone = body.timezone
    await db.flush()
    merchant = await merchant_of(db, user)
    return CabinetProfileOut(
        user_id=user.id,
        email=user.email,
        timezone=user.timezone,
        merchant_id=merchant.id,
        title=merchant.title,
        status=merchant.status,
        balance_usd=await deposit.deposit_balance(db, merchant_id=merchant.id),
        offer_version=user.offer_version,
        offer_accepted_at=user.offer_accepted_at,
    )


@router.get(
    "/summary",
    response_model=CabinetSummaryOut,
    summary="Orders, deliveries and spend since a moment",
)
async def summary(user: CurrentUser, db: Db, since: datetime) -> CabinetSummaryOut:
    """``since`` is required and comes from the **browser**.

    The cabinet renders every timestamp in the viewer's own zone, so the
    browser is what knows when its day started. A server deciding "today" from
    the stored `timezone` would print a count that disagreed with the dates on
    the Orders list two screens over — and that field means "when we mail you"
    (ADR-0076), not "how to read your clock".
    """
    merchant = await merchant_of(db, user)
    return await cabinet_summary.build(
        db, merchant_id=merchant.id, since=since, now=datetime.now(UTC)
    )


@router.get("/catalog", response_model=MerchantCatalogOut, summary="The wholesale price list")
async def catalog(user: CurrentUser, db: Db) -> MerchantCatalogOut:
    """The same tree the machine API serves, priced for this merchant.

    One builder, so the storefront a person browses and the JSON their server
    polls can never disagree about what is sellable or what it costs.
    """
    return await price_list.build(db, merchant=await merchant_of(db, user))


#: Marks an order placed from the cabinet rather than by a reseller's server.
#: Read back by the frontend (three screens hide the "your id" row on it), so
#: it is one spelling here and not a literal at each site.
_MANUAL_PREFIX = "manual-"


def _manual_order_id(key: str | None) -> str:
    """The ``merchant_order_id`` for a cabinet purchase.

    Deterministic in the caller's idempotency key, so a retry of one click is
    one order; random when there is no key. See :func:`place_order` for why it
    is a digest of the header and not the header.
    """
    if key is None:
        return f"{_MANUAL_PREFIX}{new_id()}"
    return f"{_MANUAL_PREFIX}{hashlib.sha256(key.encode()).hexdigest()[:32]}"


@router.post(
    "/orders",
    response_model=MerchantOrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Order from the catalog page",
)
async def place_order(
    body: CabinetOrderIn,
    user: CurrentUser,
    db: Db,
    idempotency_key: IdempotencyKeyHeader = None,
) -> MerchantOrderOut:
    """Buy one SKU, deriving the ``merchant_order_id`` from the caller's key.

    ``manual-<digest>`` (spec §11): visibly not a reseller's own id, so a
    support conversation about "order acme-417" is never about one of these.

    **The key is the browser's, when it sends one.** It used to be minted here
    per call, which made every retry a second order and a second charge — and
    the cabinet's own client had already been fixed to hold one key per intent
    in React state and put it on ``Idempotency-Key``, so the header arrived on
    every request and was dropped on the floor. A POST that moves money and
    ignores the header it is handed is also the one thing AGENTS.md §9 says a
    state-changing endpoint may not do; the published exemption covers
    ``POST /merchant/v1/orders``, which is idempotent on an id the caller
    minted, not this route, which invents that id itself.

    Derived by digest rather than used verbatim: the header is client-
    controlled free text with only a minimum length enforced, while
    ``merchant_order_id`` is bounded at 128 printable non-space ASCII
    characters and becomes a path segment and part of a signed string on the
    machine API. Hashing makes the shape ours whatever the browser sent, and
    a 128-bit prefix does not collide. Scoping is unchanged — the lookup and
    ``uq_orders_idem_merchant`` are both per merchant — so two resellers who
    happen to mint the same key still get their own orders.

    With no header, one is minted as before: a double-click is then two
    orders, which a person can see in the list and ask about, and which is
    the better failure than an invented key collapsing two real purchases.
    """
    merchant = await merchant_of(db, user)
    return await orders.place(
        db,
        merchant=merchant,
        body=MerchantOrderCreateIn(
            merchant_order_id=_manual_order_id(normalize_idempotency_key(idempotency_key)),
            sku_id=body.sku_id,
            quantity=body.quantity,
            amount_usd=body.amount_usd,
            expected_price=body.expected_price,
            fulfillment_data=dict(body.fulfillment_data),
        ),
    )


@router.get("/orders", response_model=CabinetOrdersOut, summary="This merchant's orders")
async def list_orders(
    user: CurrentUser,
    db: Db,
    status_filter: str | None = None,
    search: str | None = None,
    cursor: str | None = None,
    limit: int = 25,
) -> CabinetOrdersOut:
    """Newest first, keyset-paged.

    ``status_filter`` rather than ``status``: FastAPI would otherwise shadow
    the imported ``status`` module in this file's namespace, and a name that
    silently rebinds an HTTP-status helper inside route handlers is a trap
    worth spending one uglier query parameter to avoid.
    """
    merchant = await merchant_of(db, user)
    return await cabinet_orders.build(
        db,
        merchant_id=merchant.id,
        limit=max(1, min(limit, 100)),
        cursor=cursor,
        status=status_filter,
        search=search,
    )


@router.get(
    "/orders/{merchant_order_id:path}",
    response_model=CabinetOrderDetailOut,
    summary="One order, by the id it was placed with",
)
async def read_order(merchant_order_id: str, user: CurrentUser, db: Db) -> CabinetOrderDetailOut:
    """The same reader the machine API serves, plus the product's name.

    ``cabinet_orders.read_detail`` calls the identical ``order_status.read``
    the machine API polls — the cabinet and a reseller's own polling still
    describe an order's status, timeline and delivery the same way — and adds
    ``sku_code``/``sku_name``/``brand_name`` on top, for the screen only.
    """
    return await cabinet_orders.read_detail(
        db, merchant=await merchant_of(db, user), merchant_order_id=merchant_order_id
    )


@router.get(
    "/transactions",
    response_model=MerchantTransactionsOut,
    summary="The deposit ledger",
)
async def list_transactions(
    user: CurrentUser, db: Db, cursor: str | None = None, limit: int = 50
) -> MerchantTransactionsOut:
    merchant = await merchant_of(db, user)
    return await transactions.build(
        db, merchant_id=merchant.id, limit=max(1, min(limit, 200)), cursor=cursor
    )


def _csv(body: tuple[str, str]) -> Response:
    """A CSV download, named so the file says what it holds."""
    text, filename = body
    return Response(
        # BOM first: Excel reads a CSV without one as the system codepage and
        # renders every Cyrillic brand name as mojibake. Every other reader
        # tolerates it.
        content="\ufeff" + text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/orders.csv", summary="The order history, as CSV")
async def export_orders(user: CurrentUser, db: Db) -> Response:
    """The same reader the Заказы screen pages through, money included."""
    merchant = await merchant_of(db, user)
    return _csv(await cabinet_export.orders_csv(db, merchant_id=merchant.id))


@router.get("/transactions.csv", summary="The deposit statement, as CSV")
async def export_transactions(user: CurrentUser, db: Db) -> Response:
    """Built from the same reader the Транзакции screen pages through.

    A statement disagreeing with the screen about what a merchant spent is
    worse than no statement, and one source is the only way that cannot
    happen.
    """
    merchant = await merchant_of(db, user)
    return _csv(await cabinet_export.statement_csv(db, merchant_id=merchant.id))


@router.get("/catalog.csv", summary="The wholesale price list, as CSV")
async def export_catalog(user: CurrentUser, db: Db) -> Response:
    """The same tree ``GET /catalog`` serves, flattened to one row per SKU."""
    return _csv(await cabinet_export.price_list_csv(db, merchant=await merchant_of(db, user)))


@router.get("/api-keys", response_model=list[CabinetApiKeyOut], summary="Machine credentials")
async def list_keys(user: CurrentUser, db: Db) -> list[CabinetApiKeyOut]:
    merchant = await merchant_of(db, user)
    rows = await credentials.list_api_keys(db, merchant_id=merchant.id)
    return [CabinetApiKeyOut.model_validate(row) for row in rows]


@router.post(
    "/api-keys",
    response_model=CabinetIssuedKeyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a machine credential",
)
async def create_key(body: CabinetApiKeyCreateIn, user: CurrentUser, db: Db) -> CabinetIssuedKeyOut:
    """The secret is in this response and nowhere else, ever again.

    Self-serve rather than a support request, which is what makes rotation —
    issue, deploy, revoke — something a reseller can do at 3am during an
    incident instead of waiting for our morning.
    """
    merchant = await merchant_of(db, user)
    issued = await credentials.create_api_key(
        db, merchant_id=merchant.id, label=body.label, ip_allowlist=body.ip_allowlist
    )
    log.info("merchant.cabinet.key_created", merchant_id=merchant.id, key_id=issued.key.key_id)
    await cabinet_notify.notify_security(
        db, merchant_id=merchant.id, event="api_key_created", detail=issued.key.key_id
    )
    return CabinetIssuedKeyOut(
        key_id=issued.key.key_id,
        secret=issued.secret,
        label=issued.key.label,
        ip_allowlist=issued.key.ip_allowlist,
        created_at=issued.key.created_at,
    )


@router.delete(
    "/api-keys/{key_id}",
    response_model=CabinetApiKeyOut,
    summary="Revoke a machine credential",
)
async def revoke_key(key_id: str, user: CurrentUser, db: Db) -> CabinetApiKeyOut:
    merchant = await merchant_of(db, user)
    row = await credentials.revoke_api_key(db, merchant_id=merchant.id, key_id=key_id)
    log.info("merchant.cabinet.key_revoked", merchant_id=merchant.id, key_id=key_id)
    await cabinet_notify.notify_security(
        db, merchant_id=merchant.id, event="api_key_revoked", detail=row.key_id
    )
    return CabinetApiKeyOut.model_validate(row)


__all__ = ["router"]
