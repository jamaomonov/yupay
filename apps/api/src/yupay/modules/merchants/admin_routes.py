"""Admin HTTP routes for the merchant B2B programme (M1, Task 6).

``admin_router`` under ``/admin/merchants``, admin-gated like
``affiliate.routes.admin_router`` — create/list/freeze/unfreeze, the deposit
credit, the machine credentials and the webhook configuration. The B2B knobs
that live on catalog rows are the sibling ``catalog_b2b_router`` in
:mod:`yupay.modules.merchants.catalog_b2b_routes`, split out of this file
when it passed AGENTS.md §6's split-before-500 line; the two share the replay
helpers in :mod:`yupay.modules.merchants.route_replay`.

Business logic is imported through the ``merchants.api`` facade only —
routers parse and dispatch (AGENTS.md §6). Every write accepts
``Idempotency-Key`` (§9): the deposit credit REQUIRES it (the header is the
client half of the namespaced ledger key, ``merchant-credit:{merchant_id}:
{client_key}`` — wallet-gateway style, so one client's key can never replay
another merchant's transaction), while the rest replay through the generic
``(scope, key)`` store the other admin write endpoints use.

``api/v1`` imports this router from here, not from the facade — the facade
is imported by service-layer callers, and a router re-exported from it would
close a cycle back through the v1 route stack (the ``affiliate.routes``
precedent, same comment there).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.api.v1.deps import db_session
from yupay.core.errors import ValidationError
from yupay.core.idempotency import (
    IDEMPOTENCY_HEADER,
    MIN_IDEMPOTENCY_KEY_LENGTH,
    normalize_idempotency_key,
)
from yupay.modules.admin.api import require_admin
from yupay.modules.merchants import api as merchants
from yupay.modules.merchants.cabinet_schemas import CabinetDeliveriesOut
from yupay.modules.merchants.route_replay import IdempotencyKeyHeader, remember, replayed
from yupay.modules.merchants.schemas import (
    ApiKeyCreatedOut,
    ApiKeyCreateIn,
    ApiKeyListOut,
    ApiKeyOut,
    DepositCreditIn,
    DepositCreditOut,
    DepositDebitIn,
    DepositDebitOut,
    MerchantCreateIn,
    MerchantListOut,
    MerchantOut,
    MerchantTxnListOut,
    MerchantTxnOut,
    MerchantUserListOut,
    WebhookOut,
    WebhookSecretOut,
    WebhookSetIn,
)
from yupay.modules.users.models import User

admin_router = APIRouter(
    prefix="/admin/merchants",
    tags=["admin:merchants"],
    dependencies=[Depends(require_admin)],
)

#: Cap on the CLIENT half of the deposit-credit key. The ledger column is
#: ``String(160)`` and the ``merchant-credit:{uuid}:`` prefix consumes 53
#: chars, so anything over 107 overflows into a ``DataError`` — which
#: ``post()``'s ``except IntegrityError`` does not catch — i.e. a
#: deterministic 500 on every retry of the same long key. 100 leaves margin
#: under that ceiling; reject at the parse boundary with a readable 422.
MAX_DEPOSIT_CLIENT_KEY_LENGTH = 100


def _webhook_secret_out(configured: merchants.ConfiguredWebhook) -> WebhookSecretOut:
    """Render a just-written webhook, carrying the secret only if one was minted."""
    return WebhookSecretOut(
        **WebhookOut.model_validate(configured.webhook).model_dump(), secret=configured.secret
    )


def _merchant_out(merchant: merchants.Merchant, balance: Decimal) -> MerchantOut:
    return MerchantOut(
        id=merchant.id,
        title=merchant.title,
        status=merchant.status,
        created_at=merchant.created_at,
        deposit_balance=balance,
    )


@admin_router.post(
    "",
    response_model=MerchantOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a reseller account",
)
async def create_merchant(
    body: MerchantCreateIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> MerchantOut:
    """Create a merchant; a retried key replays the original row."""
    # Known limitation of piggybacking the generic replay store on a CREATE:
    # ``save_replay`` swallows the losing side of a same-key race ("the
    # caller's own response is equivalent"), which is true for the
    # mutate-existing endpoints it was built for and NOT here — two
    # concurrent same-key creates can both insert, one snapshot silently
    # loses, and two merchant rows exist. Admin-only surface, sequential
    # replays (the actual retry case) are correct, so this is accepted —
    # not a bug to rediscover in production.
    key = normalize_idempotency_key(idempotency_key)
    scope = "merchants.create"
    cached = await replayed(db, scope=scope, key=key, model=MerchantOut)
    if cached is not None:
        return cached
    merchant = await merchants.create_merchant(db, title=body.title)
    out = _merchant_out(merchant, Decimal("0"))
    await remember(
        db,
        scope=scope,
        key=key,
        body=out.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
    )
    return out


@admin_router.get(
    "",
    response_model=MerchantListOut,
    summary="Every merchant, with its USD deposit balance",
)
async def list_merchants(
    db: Annotated[AsyncSession, Depends(db_session)],
) -> MerchantListOut:
    """One grouped query, not a balance read per merchant (AGENTS.md §10)."""
    rows = await merchants.list_merchants_with_balances(db)
    return MerchantListOut(items=[_merchant_out(m, balance) for m, balance in rows])


@admin_router.post(
    "/{merchant_id}/freeze",
    response_model=MerchantOut,
    summary="Freeze a merchant (blocks orders in M2, never money in)",
)
async def freeze_merchant(
    merchant_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> MerchantOut:
    """Persist ``status=frozen``. In M1 nothing is blocked yet — see the module README."""
    return await _set_status(db, merchant_id=merchant_id, to="frozen", key=idempotency_key)


@admin_router.post(
    "/{merchant_id}/unfreeze",
    response_model=MerchantOut,
    summary="Reactivate a frozen merchant",
)
async def unfreeze_merchant(
    merchant_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> MerchantOut:
    """Persist ``status=active``."""
    return await _set_status(db, merchant_id=merchant_id, to="active", key=idempotency_key)


async def _set_status(
    db: AsyncSession, *, merchant_id: str, to: str, key: str | None
) -> MerchantOut:
    """Shared freeze/unfreeze body: replay, mutate, remember."""
    normalized = normalize_idempotency_key(key)
    scope = f"merchants.set_status.{to}:{merchant_id}"
    cached = await replayed(db, scope=scope, key=normalized, model=MerchantOut)
    if cached is not None:
        return cached
    merchant = await merchants.set_status(db, merchant_id=merchant_id, status=to)
    balance = await merchants.deposit_balance(db, merchant_id=merchant_id)
    out = _merchant_out(merchant, balance)
    # The snapshot freezes ``deposit_balance`` as of the FIRST call — a
    # replayed response can show a stale balance if credits landed in
    # between. ``GET /admin/merchants`` is the authoritative balance read.
    await remember(db, scope=scope, key=normalized, body=out.model_dump(mode="json"))
    return out


@admin_router.post(
    "/{merchant_id}/deposit-credits",
    response_model=DepositCreditOut,
    status_code=status.HTTP_201_CREATED,
    summary="Credit a merchant's USD deposit (idempotent via key)",
)
async def credit_deposit(
    merchant_id: str,
    body: DepositCreditIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> DepositCreditOut:
    """Book ``D merchant_deposit / C house_payments_received`` on the ledger.

    The ``Idempotency-Key`` header is REQUIRED: it is the client half of the
    namespaced ledger key, so an admin retry after a timeout replays the
    original transaction instead of crediting twice. The ledger replays by
    key WITHOUT comparing parameters — a reused key with an amended amount or
    an amended ``order_id`` returns the old transaction and books nothing — so
    the response's ``amount`` and ``order_id`` are the replayed transaction's,
    making the mismatch visible to the admin UI.

    An optional ``order_id`` names the order this credit settles: the amount
    then shows on that order's ``refunded_usd`` and reconciles on the
    merchant's own statement, which is how a hand settlement after a failed
    delivery stops being invisible to the merchant it was paid to. It must be
    an order of **this** merchant's; one that is not answers ``404
    order_not_found``, identically to an id that never existed.

    Since M3b Task 3 an attributed credit that would take the order past what
    it charged answers ``409 order_already_settled``. Most failed deliveries
    now settle themselves within seconds, so the operator reaching for this
    form is the one most likely to be acting on what they saw a minute ago,
    and ``refunded_usd`` is published to the merchant as "how much of
    ``price_usd`` came back". Goodwill beyond the order's own price is an
    **unattributed** credit — omit ``order_id``.
    """
    if not idempotency_key or len(idempotency_key) < MIN_IDEMPOTENCY_KEY_LENGTH:
        raise ValidationError(
            f"Idempotency-Key header is required (>={MIN_IDEMPOTENCY_KEY_LENGTH} chars)",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    if len(idempotency_key) > MAX_DEPOSIT_CLIENT_KEY_LENGTH:
        raise ValidationError(
            f"Idempotency-Key header must be <={MAX_DEPOSIT_CLIENT_KEY_LENGTH} chars "
            "on this endpoint — it is namespaced into a bounded ledger column",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    txn = await merchants.credit_deposit(
        db,
        merchant_id=merchant_id,
        amount=body.amount,
        actor=f"admin:{admin.id}",
        idempotency_key=f"merchant-credit:{merchant_id}:{idempotency_key}",
        note=body.note,
        order_id=body.order_id,
    )
    balance = await merchants.deposit_balance(db, merchant_id=merchant_id)
    # Both legs carry the same amount; either one is the transaction's amount —
    # on a replay this is the ORIGINAL amount, not the request's. The same
    # holds for the reference, which is read back through the module's own
    # reader rather than re-derived from ``body.order_id``: on a replay those
    # two are exactly the pair that can disagree.
    return DepositCreditOut(
        transaction_id=txn.id,
        merchant_id=merchant_id,
        amount=txn.postings[0].amount,
        balance=balance,
        order_id=merchants.order_reference_of(txn),
    )


@admin_router.post(
    "/{merchant_id}/deposit-debits",
    response_model=DepositDebitOut,
    status_code=status.HTTP_201_CREATED,
    summary="Debit a merchant's USD deposit (idempotent via key)",
)
async def debit_deposit(
    merchant_id: str,
    body: DepositDebitIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> DepositDebitOut:
    """Book ``C merchant_deposit / D house_payments_received`` on the ledger.

    The operator's correction: a top-up credited in error, a test balance
    being zeroed, money settled with a reseller outside the system. It is the
    exact mirror of ``deposit-credits`` and shares its rules — the
    ``Idempotency-Key`` header is REQUIRED and is the client half of the
    namespaced ledger key, and the ledger replays by key WITHOUT comparing
    parameters, so the response echoes the POSTED amount rather than the
    request's.

    Two things differ from the credit, both deliberate:

    ``reason`` is required. A debit's justification is the only one that lives
    entirely outside the system — no order, no supplier outcome, no payment —
    so the ledger row is the only place it can be recorded, and it is what the
    detail screen's audit trail shows.

    There is no ``order_id``. A debit is booked against the merchant; pointing
    it at an order would put it on that order's ``refunded_usd``, publishing
    money the merchant never got back. Taking back a credit that DID settle an
    order is still a debit — the order's settlement is a separate fact and
    correcting it is ``deposit-credits`` territory, not this.

    A debit may not take the balance below zero: ``409 insufficient_deposit``,
    the same code and the same locked-row guard the order path uses, so a
    debit racing an order charge cannot overdraw between them. A FROZEN
    merchant may be debited — freezing blocks orders, never the ledger.

    The merchant is NOT notified. There is no ``balance.debited`` in the
    published webhook set and this endpoint does not invent one; the movement
    appears on their ``/merchant/v1/transactions`` with its own ``kind``.
    """
    if not idempotency_key or len(idempotency_key) < MIN_IDEMPOTENCY_KEY_LENGTH:
        raise ValidationError(
            f"Idempotency-Key header is required (>={MIN_IDEMPOTENCY_KEY_LENGTH} chars)",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    if len(idempotency_key) > MAX_DEPOSIT_CLIENT_KEY_LENGTH:
        raise ValidationError(
            f"Idempotency-Key header must be <={MAX_DEPOSIT_CLIENT_KEY_LENGTH} chars "
            "on this endpoint — it is namespaced into a bounded ledger column",
            extra={"header": IDEMPOTENCY_HEADER},
        )
    txn = await merchants.debit_deposit(
        db,
        merchant_id=merchant_id,
        amount=body.amount,
        actor=f"admin:{admin.id}",
        idempotency_key=merchants.debit_key(merchant_id, idempotency_key),
        reason=body.reason,
    )
    balance = await merchants.deposit_balance(db, merchant_id=merchant_id)
    # Both legs carry the same amount; either one is the transaction's — and
    # on a replay it is the ORIGINAL amount, which is what makes a reused key
    # with an amended amount visible to the admin UI instead of silent.
    return DepositDebitOut(
        transaction_id=txn.id,
        merchant_id=merchant_id,
        amount=txn.postings[0].amount,
        balance=balance,
    )


@admin_router.get(
    "/{merchant_id}/transactions",
    response_model=MerchantTxnListOut,
    summary="A merchant's deposit ledger, newest first",
)
async def list_merchant_transactions(
    merchant_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MerchantTxnListOut:
    """Every ledger movement of this merchant's deposit — the detail screen's audit trail.

    Read-only, one grouped query; ``amount`` is the signed deposit delta
    (positive = balance up). ``limit`` is bounded 1..200 in the contract —
    out-of-range values are a 422, not a silent clamp.
    """
    rows = await merchants.list_deposit_transactions(db, merchant_id=merchant_id, limit=limit)
    items: list[MerchantTxnOut] = []
    for txn, amount in rows:
        note = txn.extra_metadata.get(merchants.OPERATOR_NOTE_KEY)
        items.append(
            MerchantTxnOut(
                transaction_id=txn.id,
                kind=txn.kind,
                amount=amount,
                note=note if isinstance(note, str) else None,
                actor=txn.actor,
                created_at=txn.created_at,
            )
        )
    return MerchantTxnListOut(items=items)


@admin_router.post(
    "/{merchant_id}/api-keys",
    response_model=ApiKeyCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a machine credential for /merchant/v1",
)
async def create_api_key(
    merchant_id: str,
    body: ApiKeyCreateIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiKeyCreatedOut:
    """Mint a key. The secret is in this response and nowhere else, ever.

    Several live keys per merchant are supported so rotation has no downtime
    window (spec §9.2): issue, deploy, then revoke the old one.

    A retry carrying the same ``Idempotency-Key`` replays the original
    ``key_id`` but with ``secret: null`` — the stored snapshot deliberately
    omits it, because ``idempotent_responses`` has no reaper and a usable
    credential must not sit there in the clear. If the first response was
    lost, revoke the key and issue another.
    """
    key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.api_key_create:{merchant_id}"
    cached = await replayed(db, scope=scope, key=key, model=ApiKeyCreatedOut)
    if cached is not None:
        return cached
    issued = await merchants.create_api_key(
        db, merchant_id=merchant_id, label=body.label, ip_allowlist=body.ip_allowlist
    )
    out = ApiKeyCreatedOut(
        **ApiKeyOut.model_validate(issued.key).model_dump(), secret=issued.secret
    )
    await remember(
        db,
        scope=scope,
        key=key,
        body=out.model_copy(update={"secret": None}).model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
    )
    return out


@admin_router.get(
    "/{merchant_id}/api-keys",
    response_model=ApiKeyListOut,
    summary="A merchant's machine credentials, newest first",
)
async def list_api_keys(
    merchant_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> ApiKeyListOut:
    """Never returns a secret — the response model has no such field.

    Revoked keys stay listed: "which credential was live at the time" is the
    question this screen answers.
    """
    rows = await merchants.list_api_keys(db, merchant_id=merchant_id)
    return ApiKeyListOut(items=[ApiKeyOut.model_validate(row) for row in rows])


@admin_router.delete(
    "/{merchant_id}/api-keys/{key_id}",
    response_model=ApiKeyOut,
    summary="Revoke a machine credential",
)
async def revoke_api_key(
    merchant_id: str,
    key_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiKeyOut:
    """Set ``revoked_at``; the key stops authenticating immediately.

    Naturally idempotent — a second call returns the row with the FIRST
    revocation timestamp rather than moving it — and the key is matched on
    ``(merchant_id, key_id)``, so one merchant's id in the path cannot revoke
    another's credential (404 instead).
    """
    replay_key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.api_key_revoke:{merchant_id}:{key_id}"
    cached = await replayed(db, scope=scope, key=replay_key, model=ApiKeyOut)
    if cached is not None:
        return cached
    row = await merchants.revoke_api_key(db, merchant_id=merchant_id, key_id=key_id)
    out = ApiKeyOut.model_validate(row)
    await remember(db, scope=scope, key=replay_key, body=out.model_dump(mode="json"))
    return out


@admin_router.put(
    "/{merchant_id}/webhook",
    response_model=WebhookSecretOut,
    summary="Point a merchant's outgoing webhook at a URL",
)
async def set_webhook(
    merchant_id: str,
    body: WebhookSetIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> WebhookSecretOut:
    """Set the endpoint. The secret is in this response and nowhere else, ever.

    An upsert, because v1 allows one endpoint per merchant: the first call
    mints the signing secret and returns it once; a later call edits the URL
    of the same row and answers ``secret: null``, because changing where
    deliveries go must not silently break a working verifier. Setting a URL
    also clears ``disabled_at`` and the failure streak — that is the recovery
    path after an auto-disable.

    Admin-only in M3a by owner decision; the merchant gets this control from
    the cabinet in M4. A ``/merchant/v1`` write would exist only to let a
    stranger aim our worker at an address of their choosing.

    A retry carrying the same ``Idempotency-Key`` replays the original
    response with ``secret: null`` — ``idempotent_responses`` has no reaper,
    so a usable signing key must not be persisted there. If the first
    response was lost, rotate.
    """
    key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.webhook_set:{merchant_id}"
    cached = await replayed(db, scope=scope, key=key, model=WebhookSecretOut)
    if cached is not None:
        return cached
    configured = await merchants.set_webhook(db, merchant_id=merchant_id, url=body.url)
    out = _webhook_secret_out(configured)
    await remember(
        db,
        scope=scope,
        key=key,
        body=out.model_copy(update={"secret": None}).model_dump(mode="json"),
    )
    return out


@admin_router.get(
    "/{merchant_id}/webhook",
    response_model=WebhookOut,
    summary="A merchant's webhook configuration and its delivery health",
)
async def read_webhook(
    merchant_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> WebhookOut:
    """Never returns the secret — the response model has no such field.

    404 both when the merchant does not exist and when it has never
    registered an endpoint.
    """
    return WebhookOut.model_validate(await merchants.get_webhook(db, merchant_id=merchant_id))


@admin_router.get(
    "/{merchant_id}/webhook/deliveries",
    response_model=CabinetDeliveriesOut,
    summary="A merchant's webhook delivery attempts, newest first",
)
async def read_webhook_deliveries(
    merchant_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query()] = None,
) -> CabinetDeliveriesOut:
    """The same log the merchant reads in their own cabinet.

    One reader, ``cabinet_webhooks.list_deliveries``, not a second query:
    support asking "what did we send you" must see exactly what the reseller
    sees, and two queries over one table is how those two answers start to
    differ. It takes ``merchant_id`` as an argument rather than off a
    session, which is what makes it reusable here at all.

    The rows carry the request body we sent and the response we got, so this
    is an admin route and stays one.
    """
    return await merchants.list_deliveries(db, merchant_id=merchant_id, limit=limit, cursor=cursor)


@admin_router.get(
    "/{merchant_id}/users",
    response_model=MerchantUserListOut,
    summary="Who can sign into this merchant's cabinet",
)
async def read_merchant_users(
    merchant_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> MerchantUserListOut:
    """Operators, with whether the address is confirmed and when they last got in.

    ``last_login_at`` is derived from ``merchant_sessions`` — see
    ``operators.list_operators``. It answers the half of "I cannot sign in"
    that a password reset does not: never confirmed, or never signed in at
    all, is a different conversation from signed in last month.

    Returns e-mail addresses, which is why it is admin-only and why nothing
    in the path logs them.
    """
    return await merchants.list_operators(db, merchant_id=merchant_id)


@admin_router.post(
    "/{merchant_id}/webhook/rotate-secret",
    response_model=WebhookSecretOut,
    summary="Replace a merchant's webhook signing secret",
)
async def rotate_webhook_secret(
    merchant_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> WebhookSecretOut:
    """Mint a new secret and return it once; the old one stops signing immediately.

    One live key at a time, unlike the machine credential's overlapping
    rotation — there the merchant redeploys between issue and revoke and only
    they know when that finished, whereas here we are the sender and the
    switch is ours to make. A replay answers ``secret: null`` rather than
    rotating a second time.
    """
    key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.webhook_rotate:{merchant_id}"
    cached = await replayed(db, scope=scope, key=key, model=WebhookSecretOut)
    if cached is not None:
        return cached
    configured = await merchants.rotate_webhook_secret(db, merchant_id=merchant_id)
    out = _webhook_secret_out(configured)
    await remember(
        db,
        scope=scope,
        key=key,
        body=out.model_copy(update={"secret": None}).model_dump(mode="json"),
    )
    return out


@admin_router.delete(
    "/{merchant_id}/webhook",
    response_model=WebhookOut,
    summary="Disable a merchant's webhook (keeps the row and its log)",
)
async def disable_webhook(
    merchant_id: str,
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: IdempotencyKeyHeader = None,
) -> WebhookOut:
    """Set ``disabled_at``; nothing is enqueued or delivered while it is set.

    Naturally idempotent — a second call returns the FIRST timestamp rather
    than moving it — and it is a disable, not a delete: the row and the
    delivery log stay readable, and re-enabling is a ``PUT`` with the URL.
    """
    replay_key = normalize_idempotency_key(idempotency_key)
    scope = f"merchants.webhook_disable:{merchant_id}"
    cached = await replayed(db, scope=scope, key=replay_key, model=WebhookOut)
    if cached is not None:
        return cached
    out = WebhookOut.model_validate(await merchants.disable_webhook(db, merchant_id=merchant_id))
    await remember(db, scope=scope, key=replay_key, body=out.model_dump(mode="json"))
    return out


__all__ = ["admin_router"]
