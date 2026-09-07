"""Merchant accounts, their machine credentials, and the USD deposit ledger.

M1 scope (spec §7): support credits a merchant's prepaid deposit through the
admin surface, and the cabinet reads the balance. M2 adds the other direction
— ``charge_deposit``, which the machine API's order path calls, and which is
where the overdraw guard actually binds. The deposit is a ledger balance,
never a column — ``merchant_deposit`` is debit-normal exactly like
``user_wallet``, and every movement goes through ``wallet.service.post`` so
idempotency-by-key and all-or-nothing legs are inherited, not rebuilt. The
full posting table (including the M2 rows) lives in this module's README.

Reaches into ``wallet.service`` rather than the ``wallet.api`` facade for the
same reason ``affiliate/ledger.py`` does: the facade imports the wallet
router, which pulls in the whole v1 route stack and circles straight back —
an ImportError for any caller that is not already inside the app.

Freezing a merchant (``set_status``) blocks ORDERS — from M2 on, the
``merchant_auth`` dependency refuses a frozen merchant with 403
``merchant_frozen`` — never money in: support can always credit a frozen
merchant's deposit, e.g. to settle a dispute while the account is under
review.

M2 adds the credential lifecycle (``create_api_key`` / ``list_api_keys`` /
``revoke_api_key``). It lives here, next to the account it belongs to,
rather than in ``auth``: ``auth`` binds to the request stack (it is a
FastAPI dependency) and therefore cannot be re-exported from ``api`` without
closing an import cycle, while these three are ordinary row operations the
admin surface calls through the facade like everything else. The wire format
they mint into is ``signing``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core import crypto
from yupay.core.clock import now
from yupay.core.errors import ConflictError, NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.modules.merchants import signing
from yupay.modules.merchants.models import Merchant, MerchantApiKey
from yupay.modules.wallet import service as wallet_service
from yupay.modules.wallet.models import WalletAccount, WalletTransaction

#: The deposit is USD-only in v1 (spec §7): merchants settle invoices in USD
#: and every SKU already carries a USD cost basis. A second currency would be
#: a new account row per merchant, not a schema change.
DEPOSIT_CURRENCY = "USD"

_STATUSES = ("active", "frozen")
_HOUSE_OWNER = "house"
_CENT = Decimal("0.01")

#: RFC 7807 ``code`` for an order the deposit cannot cover (spec §9.4). Lives
#: here, beside the guard that raises it, so the machine API and the ledger
#: cannot spell it differently.
INSUFFICIENT_DEPOSIT_CODE = "insufficient_deposit"


async def _get_merchant(db: AsyncSession, merchant_id: str) -> Merchant:
    """Load a merchant row or raise.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The ``merchants.id`` to load.

    Returns:
        The merchant row.

    Raises:
        NotFoundError: If no merchant with that id exists.
    """
    merchant = (
        await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    ).scalar_one_or_none()
    if merchant is None:
        raise NotFoundError("merchant not found")
    return merchant


async def create_merchant(db: AsyncSession, *, title: str) -> Merchant:
    """Create a reseller account.

    Args:
        db: Session. The caller owns the transaction.
        title: Human-readable merchant name, non-blank.

    Returns:
        The new merchant, with server defaults (``status``, ``created_at``)
        populated.

    Raises:
        ValidationError: If ``title`` is blank.
    """
    cleaned = title.strip()
    if not cleaned:
        raise ValidationError("merchant title must not be blank")
    merchant = Merchant(id=new_id(), title=cleaned)
    db.add(merchant)
    await db.flush()
    # Pick up the server-side defaults so callers see status='active' without
    # a round-trip of their own.
    await db.refresh(merchant)
    return merchant


async def set_status(db: AsyncSession, *, merchant_id: str, status: str) -> Merchant:
    """Set a merchant's status to ``active`` or ``frozen``.

    Freezing blocks new orders (enforced by the M2 order path), not deposits —
    see the module docstring.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose status to change.
        status: One of ``active`` / ``frozen``.

    Returns:
        The updated merchant row.

    Raises:
        ValidationError: If ``status`` is not a known value.
        NotFoundError: If no merchant with that id exists.
    """
    if status not in _STATUSES:
        raise ValidationError(
            "merchant status must be 'active' or 'frozen'", extra={"status": status}
        )
    merchant = await _get_merchant(db, merchant_id)
    merchant.status = status
    await db.flush()
    return merchant


@dataclass(frozen=True)
class IssuedApiKey:
    """A freshly minted credential: the stored row plus the one-time secret.

    ``secret`` exists in the clear only in this object and in the HTTP
    response that carries it. It is never logged and never returned again —
    the row holds it encrypted (``core.crypto``), which is what lets the
    signature be verified at all without keeping key material in the clear.
    """

    key: MerchantApiKey
    secret: str


async def create_api_key(
    db: AsyncSession,
    *,
    merchant_id: str,
    label: str = "",
    ip_allowlist: list[str] | None = None,
) -> IssuedApiKey:
    """Issue a machine credential for ``/merchant/v1``.

    Several live keys per merchant are supported on purpose (spec §9.2):
    rotation is "issue the new one, deploy it, revoke the old one", which has
    no downtime window. Nothing here revokes anything.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Who the key belongs to. Must exist.
        label: Operator-facing note, e.g. ``"prod server"``. Trimmed.
        ip_allowlist: Addresses or CIDR blocks allowed to use this key.
            An empty list is normalised to ``None`` (filter off) so the
            "no addresses at all" shape can never reach the auth path — see
            ``auth.address_allowed``.

    Returns:
        The new row plus the plaintext secret, which the caller must return
        to the operator immediately and then forget. The row stores it
        encrypted under ``core.crypto``'s merchant-API purpose key.

    Raises:
        NotFoundError: If no merchant with that id exists.
    """
    await _get_merchant(db, merchant_id)
    secret = signing.new_secret()
    secret_enc, secret_nonce = crypto.encrypt(secret, purpose=crypto.PURPOSE_MERCHANT_API_KEY)
    key = MerchantApiKey(
        id=new_id(),
        merchant_id=merchant_id,
        key_id=signing.new_key_id(),
        secret_enc=secret_enc,
        secret_nonce=secret_nonce,
        label=label.strip(),
        ip_allowlist=ip_allowlist or None,
    )
    db.add(key)
    await db.flush()
    # Pick up ``created_at``'s server default so the caller can render the row
    # without a round-trip of its own.
    await db.refresh(key)
    return IssuedApiKey(key=key, secret=secret)


async def list_api_keys(db: AsyncSession, *, merchant_id: str) -> list[MerchantApiKey]:
    """Every key ever issued to a merchant, newest first, revoked ones included.

    Revoked keys stay listed: "which credential was live when this happened"
    is the question the cabinet's security page exists to answer.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose keys to list. Must exist.

    Returns:
        The rows, newest first.

    Raises:
        NotFoundError: If no merchant with that id exists — an empty list for
            a typo'd id must be a 404, not a plausible-looking ``[]``.
    """
    await _get_merchant(db, merchant_id)
    stmt = (
        select(MerchantApiKey)
        .where(MerchantApiKey.merchant_id == merchant_id)
        # ``created_at`` is transaction-start time, so two keys minted in one
        # transaction tie; the UUIDv7 id is the monotonic tiebreak.
        .order_by(MerchantApiKey.created_at.desc(), MerchantApiKey.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def revoke_api_key(db: AsyncSession, *, merchant_id: str, key_id: str) -> MerchantApiKey:
    """Revoke a key. Idempotent: a second call leaves the first timestamp alone.

    The key is matched on ``(merchant_id, key_id)`` rather than ``key_id``
    alone, so one merchant's id in the path can never revoke another's
    credential.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The owning merchant. Must exist.
        key_id: The public half of the credential to revoke.

    Returns:
        The row, with ``revoked_at`` set.

    Raises:
        NotFoundError: If the merchant does not exist, or the key does not
            belong to it.
    """
    await _get_merchant(db, merchant_id)
    key = (
        await db.execute(
            select(MerchantApiKey).where(
                MerchantApiKey.merchant_id == merchant_id,
                MerchantApiKey.key_id == key_id,
            )
        )
    ).scalar_one_or_none()
    if key is None:
        raise NotFoundError("api key not found")
    if key.revoked_at is None:
        key.revoked_at = now()
        await db.flush()
    return key


async def credit_deposit(
    db: AsyncSession,
    *,
    merchant_id: str,
    amount: Decimal,
    actor: str,
    idempotency_key: str,
    note: str | None = None,
) -> WalletTransaction:
    """Book a support-credited top-up: ``D merchant_deposit / C house_payments_received``.

    Posts through ``wallet.service.post`` with the caller's idempotency key —
    a replay with the same key returns the original transaction (``post()``
    already guarantees it), so an admin retry after a timeout cannot credit
    twice.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Who gets the money. Must exist; may be frozen.
        amount: Positive USD amount.
        actor: Who did it, e.g. ``admin:<id>`` — recorded on the transaction.
        idempotency_key: The caller's key; the replay handle.
        note: Optional free-text reason, kept in the transaction metadata.

    Returns:
        The ledger transaction (existing one on replay).

    Raises:
        ValidationError: If ``amount`` is not positive.
        NotFoundError: If no merchant with that id exists.
    """
    if amount <= 0:
        raise ValidationError("deposit credit must be positive", extra={"amount": str(amount)})
    await _get_merchant(db, merchant_id)

    deposit = await wallet_service.ensure_account(
        db,
        owner_type="merchant",
        owner_id=merchant_id,
        kind="merchant_deposit",
        currency=DEPOSIT_CURRENCY,
    )
    # Counter-account for the merchant-side debit.
    # ``house_payments_received`` (NORMAL=D) is the dedicated bucket for
    # money customers paid us directly — a merchant's bank-transferred
    # prepayment is exactly that, so no new house account is invented here.
    # See ADR-0004 for the ledger model.
    received = await wallet_service.ensure_account(
        db,
        owner_type=_HOUSE_OWNER,
        owner_id=_HOUSE_OWNER,
        kind="house_payments_received",
        currency=DEPOSIT_CURRENCY,
    )
    return await wallet_service.post(
        db,
        kind="merchant_deposit_credit",
        legs=[
            # D on merchant_deposit (NORMAL=D) → balance ↑ by ``amount``.
            wallet_service.Leg(
                account_id=deposit.id,
                direction="D",
                amount=amount,
                currency=DEPOSIT_CURRENCY,
            ),
            # C on house counter (NORMAL=D) → balanced
            # double-entry; SUM(D) == SUM(C) holds.
            wallet_service.Leg(
                account_id=received.id,
                direction="C",
                amount=amount,
                currency=DEPOSIT_CURRENCY,
            ),
        ],
        idempotency_key=idempotency_key,
        reference=wallet_service.Reference(type="merchant", id=merchant_id),
        actor=actor,
        metadata={"note": note} if note is not None else {},
    )


async def charge_deposit(
    db: AsyncSession,
    *,
    merchant_id: str,
    amount: Decimal,
    order_id: str,
) -> WalletTransaction:
    """Debit a merchant's deposit for an order: ``C merchant_deposit / D house_payments_received``.

    The exact mirror of :func:`credit_deposit`'s legs — the module README's
    posting table is authoritative and the directions are not re-derived here.
    ``merchant_deposit`` is debit-normal, so a credit posting lowers the
    balance; the house counter takes the matching debit, which is the same
    ``house_payments_received`` bucket the prepayment landed in, now being
    drawn down against goods.

    **This is the authoritative overdraw guard**, not the caller's early
    check. The deposit account row is locked with ``SELECT … FOR UPDATE``
    before the balance is read, so two concurrent orders serialise here rather
    than both reading the same pre-spend balance and both passing — the same
    shape ``wallet.service.reverse_topup`` uses for a user wallet. The caller's
    earlier read exists only to answer with a clean ``409`` before any row is
    written; it is a courtesy, and this is the invariant.

    Idempotent on ``order_id``: the ledger key is derived from it, and an
    order id is unique per ``(merchant, merchant_order_id)`` by
    ``uq_orders_idem_merchant``. So even a caller that reached this twice for
    one order would replay the first transaction rather than debit twice —
    there is no non-idempotent side path on the merchant order flow.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose deposit to draw on. Must exist.
        amount: Positive USD amount — the price the order charges.
        order_id: The order being paid for; the ledger reference and the
            replay handle.

    Returns:
        The ledger transaction (the existing one on replay).

    Raises:
        ValidationError: If ``amount`` is not positive.
        NotFoundError: If no merchant with that id exists.
        ConflictError: If the deposit cannot cover ``amount``.
    """
    if amount <= 0:
        raise ValidationError("deposit charge must be positive", extra={"amount": str(amount)})
    await _get_merchant(db, merchant_id)

    deposit = await wallet_service.ensure_account(
        db,
        owner_type="merchant",
        owner_id=merchant_id,
        kind="merchant_deposit",
        currency=DEPOSIT_CURRENCY,
    )
    locked = (
        await db.execute(
            select(WalletAccount).where(WalletAccount.id == deposit.id).with_for_update()
        )
    ).scalar_one()
    have = await wallet_service.balance(db, locked.id)
    if have < amount:
        raise ConflictError(
            "deposit balance does not cover this order",
            code=INSUFFICIENT_DEPOSIT_CODE,
            balance_usd=str(have.quantize(_CENT, rounding=ROUND_DOWN)),
            required_usd=str(amount),
        )
    received = await wallet_service.ensure_account(
        db,
        owner_type=_HOUSE_OWNER,
        owner_id=_HOUSE_OWNER,
        kind="house_payments_received",
        currency=DEPOSIT_CURRENCY,
    )
    return await wallet_service.post(
        db,
        kind="merchant_order_charge",
        legs=[
            # C on merchant_deposit (NORMAL=D) → balance ↓ by ``amount``.
            wallet_service.Leg(
                account_id=deposit.id,
                direction="C",
                amount=amount,
                currency=DEPOSIT_CURRENCY,
            ),
            # D on the house counter (NORMAL=D) → SUM(D) == SUM(C) holds.
            wallet_service.Leg(
                account_id=received.id,
                direction="D",
                amount=amount,
                currency=DEPOSIT_CURRENCY,
            ),
        ],
        idempotency_key=f"merchant-order:{order_id}",
        reference=wallet_service.Reference(type="order", id=order_id),
        actor=f"merchant:{merchant_id}",
    )


async def deposit_balance(db: AsyncSession, *, merchant_id: str) -> Decimal:
    """Return a merchant's USD deposit balance.

    A merchant that has never been credited — or does not exist — has no
    ``merchant_deposit`` account, and its balance is simply zero. The read
    creates nothing.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose balance to read.

    Returns:
        The deposit balance; ``Decimal("0")`` when no account exists.
    """
    stmt = select(WalletAccount.id).where(
        WalletAccount.owner_type == "merchant",
        WalletAccount.owner_id == merchant_id,
        WalletAccount.kind == "merchant_deposit",
        WalletAccount.currency == DEPOSIT_CURRENCY,
    )
    account_id = (await db.execute(stmt)).scalar_one_or_none()
    if account_id is None:
        return Decimal("0")
    return await wallet_service.balance(db, account_id)


__all__ = [
    "DEPOSIT_CURRENCY",
    "INSUFFICIENT_DEPOSIT_CODE",
    "IssuedApiKey",
    "charge_deposit",
    "create_api_key",
    "create_merchant",
    "credit_deposit",
    "deposit_balance",
    "list_api_keys",
    "revoke_api_key",
    "set_status",
]
