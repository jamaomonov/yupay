"""HTTP surface for the merchant cabinet (spec §11).

A **BFF**, not a second machine API. The browser never holds a merchant's HMAC
secret — that credential belongs to their server — so the cabinet signs in with
a password, carries a short-lived ``merchant_access`` JWT, and this router does
the work on their behalf.

Every route takes the merchant from ``current_merchant_user``'s result and
never from a parameter: that is the single rule keeping one reseller out of
another's catalog, deposit and orders.

**Ordering here walks the machine API's path exactly** — ``quote``, the margin
floor, the deposit charge, the fulfilment enqueue — with a minted
``manual-<uuid>`` standing in for the ``merchant_order_id`` a person should not
have to invent (spec §11). A cabinet order and an API order are therefore the
same kind of thing in history, in the ledger and in a dispute, which is what
lets the catalog page double as the no-code first purchase.

Unlike ``/merchant/v1`` this is **not** exempt from the coarse rate limit: that
exemption exists because a 429 to a signing acquirer costs money and buys
nothing (AGENTS.md §9). A password form is the opposite case, and the two
credential routes carry the two-axis ``ip_guard`` besides.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status

from yupay.core.config import get_settings
from yupay.core.errors import ValidationError
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.auth.ip_guard import guard_ip
from yupay.modules.merchants import (
    cabinet_auth,
    cabinet_export,
    cabinet_orders,
    cabinet_summary,
    credentials,
    deposit,
    order_status,
    orders,
    price_list,
    transactions,
)
from yupay.modules.merchants.cabinet_deps import CurrentUser, Db, merchant_of
from yupay.modules.merchants.cabinet_schemas import (
    CabinetApiKeyCreateIn,
    CabinetApiKeyOut,
    CabinetConfirmIn,
    CabinetIssuedKeyOut,
    CabinetLoginIn,
    CabinetOrderIn,
    CabinetOrdersOut,
    CabinetProfileOut,
    CabinetProfilePatchIn,
    CabinetRegisterIn,
    CabinetSummaryOut,
    CabinetTokenIn,
    CabinetTokensOut,
)
from yupay.modules.merchants.machine_schemas import (
    MerchantCatalogOut,
    MerchantOrderCreateIn,
    MerchantOrderOut,
    MerchantOrderStatusOut,
    MerchantTransactionsOut,
)
from yupay.modules.notifications.channels.email import EmailSendError, send_email
from yupay.modules.notifications.templates import merchant_confirm_email

log = get_logger("yupay.merchants.cabinet_routes")

router = APIRouter(prefix="/merchant/cabinet", tags=["merchant-cabinet"])


def _tokens_out(tokens: cabinet_auth.CabinetTokens) -> CabinetTokensOut:
    return CabinetTokensOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Open a merchant account and its first operator",
)
async def register(body: CabinetRegisterIn, db: Db, request: Request) -> Response:
    """Create the account and mail a confirmation link.

    Answers ``201`` with no body. The address is not echoed and no token is
    issued: registration is open, so the response must look the same to
    somebody probing addresses as to the person who owns one — and the only
    thing that proves ownership is the link.
    """
    await guard_ip(request, bucket="merchant_register", subject=body.email.lower())
    s = get_settings()
    base = s.merchant_cabinet_url.rstrip("/")
    if not base:
        # Rather than register an account whose confirmation can never arrive.
        raise ValidationError(
            "the cabinet is not configured to send mail yet",
            code="cabinet_mail_unconfigured",
        )
    user, token = await cabinet_auth.register(
        db, email=body.email, password=body.password, title=body.title
    )
    try:
        content = merchant_confirm_email(link=f"{base}/confirm?token={token}")
        await send_email(
            to=user.email,
            subject=content.subject,
            html=content.html,
            text=content.text,
        )
    except EmailSendError:
        # The account exists and the address is unconfirmed, which is a state
        # the resend endpoint can repair. Failing the request would roll the
        # registration back and lose the password they just chose.
        log.exception("merchant.cabinet.confirm_mail_failed", user_id=user.id)
    return Response(status_code=status.HTTP_201_CREATED)


@router.post("/confirm", response_model=CabinetTokensOut, summary="Confirm an address")
async def confirm(body: CabinetConfirmIn, db: Db) -> CabinetTokensOut:
    """Consume the link and sign the operator in.

    Signing them in here rather than redirecting to a login form is safe for
    the reason the link exists: holding it *is* proof of the mailbox, which is
    the same proof the password form is trying to establish.
    """
    user = await cabinet_auth.confirm_email(db, token=body.token)
    return _tokens_out(await cabinet_auth.open_session(db, user=user, settings=get_settings()))


@router.post("/login", response_model=CabinetTokensOut, summary="Sign in")
async def login(body: CabinetLoginIn, db: Db, request: Request) -> CabinetTokensOut:
    await guard_ip(request, bucket="merchant_login", subject=body.email.lower())
    return _tokens_out(await cabinet_auth.login(db, email=body.email, password=body.password))


@router.post("/refresh", response_model=CabinetTokensOut, summary="Rotate a session")
async def refresh(body: CabinetTokenIn, db: Db) -> CabinetTokensOut:
    return _tokens_out(await cabinet_auth.refresh(db, refresh_token=body.refresh_token))


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke one session",
)
async def logout(body: CabinetTokenIn, db: Db) -> Response:
    await cabinet_auth.logout(db, refresh_token=body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@router.post(
    "/orders",
    response_model=MerchantOrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Order from the catalog page",
)
async def place_order(body: CabinetOrderIn, user: CurrentUser, db: Db) -> MerchantOrderOut:
    """Buy one SKU, minting the idempotency key on the merchant's behalf.

    ``manual-<uuid>`` (spec §11): unique per click, and visibly not a
    reseller's own id, so a support conversation about "order acme-417" is
    never about one of these.

    The trade this makes, deliberately: a double-click is two orders, where an
    API caller re-sending one id gets one. A person can see both in the list
    and ask for a refund; an invented key that collapsed two intentional
    purchases into one would be the worse failure, and the browser prevents the
    common case by disabling the button.
    """
    merchant = await merchant_of(db, user)
    return await orders.place(
        db,
        merchant=merchant,
        body=MerchantOrderCreateIn(
            merchant_order_id=f"manual-{new_id()}",
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
    response_model=MerchantOrderStatusOut,
    summary="One order, by the id it was placed with",
)
async def read_order(merchant_order_id: str, user: CurrentUser, db: Db) -> MerchantOrderStatusOut:
    """The same reader the machine API serves, so the cabinet and a reseller's
    own polling can never describe one order two ways."""
    return await order_status.read(
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
    return CabinetApiKeyOut.model_validate(row)


__all__ = ["router"]
