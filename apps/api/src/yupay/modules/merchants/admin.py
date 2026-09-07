"""Admin-side operations for the merchant B2B programme (M1, spec §8.3/§10).

Everything support needs to run a pilot merchant by hand that is not already
in ``service`` or ``deposit``: the balance-joined merchant list, and the
catalog B2B knobs (per-SKU markup/visibility, per-brand visibility, and the
one-action bulk markup). Reaches into ``catalog.models`` directly — the
established pattern for cross-module row access (``integrations.merchant_feed``,
``admin.service`` do the same) — and into ``wallet.models`` for the grouped
balance read, mirroring ``deposit.deposit_balance``.

The outgoing-webhook configuration lives here too (M3a Task 1): in this
milestone support is the only way to set a merchant's endpoint, by owner
decision — the merchant gets the control from the cabinet in M4, and there is
deliberately no ``/merchant/v1`` write for it, because its only purpose would
be to let a stranger point our own worker at an address of their choosing.

The per-merchant ledger listing used to live here too; it moved to
``deposit.py`` with the rest of the deposit's reads and writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import String, case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core import crypto
from yupay.core.clock import now
from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.modules.catalog.image_url_safety import validate_public_https_url
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.merchants import signing
from yupay.modules.merchants.deposit import DEPOSIT_CURRENCY
from yupay.modules.merchants.models import Merchant, MerchantWebhook
from yupay.modules.merchants.service import get_merchant
from yupay.modules.wallet.models import WalletAccount, WalletPosting
from yupay.modules.wallet.service import NORMAL_SIDE


async def list_merchants_with_balances(db: AsyncSession) -> list[tuple[Merchant, Decimal]]:
    """Every merchant with its USD deposit balance, in one grouped query.

    The batch variant of ``service.deposit_balance``: the same
    normal-side-signed SUM over postings, grouped per merchant-owned
    ``merchant_deposit`` account and LEFT-joined onto the merchant list —
    O(1) SQL however many merchants exist (AGENTS.md §10). A merchant that
    has never been credited has no account and reads ``Decimal("0")``.

    Args:
        db: Session. The caller owns the transaction.

    Returns:
        ``(merchant, balance)`` pairs, newest merchant first.
    """
    normal = NORMAL_SIDE["merchant_deposit"]
    signed_sum = func.coalesce(
        func.sum(
            case(
                (WalletPosting.direction == normal, WalletPosting.amount),
                else_=-WalletPosting.amount,
            )
        ),
        Decimal("0"),
    )
    balances = (
        select(
            WalletAccount.owner_id.label("merchant_id"),
            signed_sum.label("balance"),
        )
        .join(WalletPosting, WalletPosting.account_id == WalletAccount.id)
        .where(
            WalletAccount.owner_type == "merchant",
            WalletAccount.kind == "merchant_deposit",
            WalletAccount.currency == DEPOSIT_CURRENCY,
        )
        .group_by(WalletAccount.owner_id)
        .subquery()
    )
    stmt = (
        select(Merchant, func.coalesce(balances.c.balance, Decimal("0")))
        # ``owner_id`` is VARCHAR (the ledger stores any owner), ``Merchant.id``
        # is UUID — cast to text or Postgres refuses the comparison.
        .outerjoin(balances, balances.c.merchant_id == Merchant.id.cast(String))
        .order_by(Merchant.created_at.desc(), Merchant.id)
    )
    rows = (await db.execute(stmt)).all()
    return [(merchant, Decimal(balance)) for merchant, balance in rows]


async def set_sku_b2b(
    db: AsyncSession,
    *,
    sku_id: str,
    markup_pct: Decimal | None = None,
    visible_b2b: bool | None = None,
) -> Sku:
    """Set a SKU's B2B markup and/or visibility; ``None`` leaves a field untouched.

    No pricing math happens here — the markup is stored verbatim and the
    order-time margin floor (``pricing.violates_margin_floor``) is what
    guards against a fat-fingered value (spec §8.3).

    Args:
        db: Session. The caller owns the transaction.
        sku_id: The ``skus.id`` to change.
        markup_pct: New ``b2b_markup_pct``, or ``None`` to keep the current one.
        visible_b2b: New merchant-catalog visibility, or ``None`` to keep it.

    Returns:
        The updated SKU row.

    Raises:
        ValidationError: If both fields are ``None``.
        NotFoundError: If no SKU with that id exists.
    """
    if markup_pct is None and visible_b2b is None:
        raise ValidationError("provide markup_pct and/or visible_b2b")
    sku = (await db.execute(select(Sku).where(Sku.id == sku_id))).scalar_one_or_none()
    if sku is None:
        raise NotFoundError("sku not found")
    if markup_pct is not None:
        sku.b2b_markup_pct = markup_pct
    if visible_b2b is not None:
        sku.visible_b2b = visible_b2b
    sku.updated_at = now()
    await db.flush()
    return sku


async def set_brand_b2b(db: AsyncSession, *, brand_id: str, visible_b2b: bool) -> Brand:
    """Flip a brand's merchant-catalog visibility.

    Effective B2B visibility is ``brand.visible_b2b AND sku.visible_b2b``
    (see the catalog models) — hiding a brand hides all its SKUs without
    touching their own flags.

    Args:
        db: Session. The caller owns the transaction.
        brand_id: The ``brands.id`` to change.
        visible_b2b: The new visibility.

    Returns:
        The updated brand row.

    Raises:
        NotFoundError: If no brand with that id exists.
    """
    brand = (await db.execute(select(Brand).where(Brand.id == brand_id))).scalar_one_or_none()
    if brand is None:
        raise NotFoundError("brand not found")
    brand.visible_b2b = visible_b2b
    brand.updated_at = now()
    await db.flush()
    return brand


async def bulk_set_markup(
    db: AsyncSession,
    *,
    markup_pct: Decimal,
    brand_slug: str | None = None,
    category_slug: str | None = None,
) -> int:
    """Set ``b2b_markup_pct`` for every SKU of a brand or a category, in one UPDATE.

    The "set all vouchers to 5%" one-action bulk (spec §8.3). Exactly one of
    ``brand_slug`` / ``category_slug`` must be given; the target must exist —
    a typo'd slug is a 404, never a silent zero-row success.

    Args:
        db: Session. The caller owns the transaction.
        markup_pct: The markup to write on every matched SKU.
        brand_slug: Target one brand's SKUs.
        category_slug: Target every SKU of every brand in one category.

    Returns:
        How many SKU rows the UPDATE touched.

    Raises:
        ValidationError: If not exactly one target is given.
        NotFoundError: If the named brand/category does not exist.
    """
    if (brand_slug is None) == (category_slug is None):
        raise ValidationError("provide exactly one of brand_slug or category")

    if brand_slug is not None:
        brand_id = (
            await db.execute(select(Brand.id).where(Brand.slug == brand_slug))
        ).scalar_one_or_none()
        if brand_id is None:
            raise NotFoundError("brand not found", extra={"brand_slug": brand_slug})
        targets = (
            select(Sku.id)
            .join(Product, Product.id == Sku.product_id)
            .where(Product.brand_id == brand_id)
        )
    else:
        category_id = (
            await db.execute(select(Category.id).where(Category.slug == category_slug))
        ).scalar_one_or_none()
        if category_id is None:
            raise NotFoundError("category not found", extra={"category": category_slug})
        targets = (
            select(Sku.id)
            .join(Product, Product.id == Sku.product_id)
            .join(Brand, Brand.id == Product.brand_id)
            .where(Brand.category_id == category_id)
        )

    result = await db.execute(
        update(Sku).where(Sku.id.in_(targets)).values(b2b_markup_pct=markup_pct, updated_at=now())
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]  # rowcount lives on CursorResult


# ---------------------------------------------------------------------------
# Outgoing webhook configuration (M3a Task 1, spec §10)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfiguredWebhook:
    """A webhook row plus the plaintext secret, when one was just minted.

    ``secret`` is ``None`` whenever the call did not create a new signing key
    — a URL change on an existing hook, or a re-enable. It exists in the clear
    only in this object and in the single HTTP response that carries it; the
    row holds it encrypted (``core.crypto``), which is what lets us sign each
    delivery without keeping key material in the clear.
    """

    webhook: MerchantWebhook
    secret: str | None


def validate_webhook_url(url: str) -> str:
    """Reject a webhook URL that is not https, or that names a non-public host.

    The **save-time** half of the SSRF story, and deliberately the same
    function the catalog's image URLs go through
    (``catalog.image_url_safety``) rather than a second copy of the blocked
    ranges — one table that can drift is enough.

    It reads *notation*, not resolved addresses, so a hostname that resolves
    publicly now and privately at delivery time passes here. That is not an
    oversight and this function must not be described as closing it: the
    control for DNS rebinding is the outbound client re-checking the address
    it actually connects to.

    Args:
        url: The candidate URL, already stripped.

    Returns:
        ``url`` unchanged, once it has passed every check.

    Raises:
        ValidationError: The URL is malformed, not https, or targets a
            loopback / private / link-local / reserved address literal.
    """
    try:
        return validate_public_https_url(url, subject="webhook URL")
    except ValueError as exc:
        raise ValidationError(str(exc), extra={"field": "url"}) from None


async def get_webhook(db: AsyncSession, *, merchant_id: str) -> MerchantWebhook:
    """The merchant's configured endpoint.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose endpoint to read. Must exist.

    Returns:
        The row, disabled ones included — "is it off, and since when" is the
        question the screen exists to answer.

    Raises:
        NotFoundError: If the merchant does not exist, or has no webhook
            configured. A merchant that never registered one and a typo'd id
            are both 404 here; the distinction is not one an operator can act
            on differently.
    """
    await get_merchant(db, merchant_id)
    hook = await _find_webhook(db, merchant_id=merchant_id)
    if hook is None:
        raise NotFoundError("webhook not configured")
    return hook


async def set_webhook(db: AsyncSession, *, merchant_id: str, url: str) -> ConfiguredWebhook:
    """Point a merchant's webhook at ``url``, minting the secret on first use.

    One endpoint per merchant in v1, so this is an upsert on the merchant:
    the first call creates the row and returns a secret the caller must show
    once and then forget; a later call edits the URL of the same row and
    returns ``secret=None``. Changing where deliveries go deliberately does
    **not** rotate the key — that would silently break a working verifier,
    and rotation has its own endpoint.

    Setting a URL also **re-enables**: ``disabled_at`` is cleared and
    ``failure_streak`` reset to 0. That is the recovery path after the
    delivery worker auto-disables a hook whose endpoint was down, and it is
    the same action whether the operator is fixing the URL or merely
    confirming the old one still stands.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose endpoint to set. Must exist.
        url: The https endpoint. Validated by :func:`validate_webhook_url`.

    Returns:
        The row, plus the plaintext secret when this call minted one.

    Raises:
        NotFoundError: If no merchant with that id exists.
        ValidationError: If the URL is refused by the save-time check.
    """
    await get_merchant(db, merchant_id)
    clean = validate_webhook_url(url.strip())
    hook = await _find_webhook(db, merchant_id=merchant_id)
    if hook is not None:
        hook.url = clean
        hook.disabled_at = None
        hook.failure_streak = 0
        hook.updated_at = now()
        await db.flush()
        return ConfiguredWebhook(webhook=hook, secret=None)

    secret = signing.new_webhook_secret()
    secret_enc, secret_nonce = crypto.encrypt(secret, purpose=crypto.PURPOSE_MERCHANT_WEBHOOK)
    hook = MerchantWebhook(
        id=new_id(),
        merchant_id=merchant_id,
        url=clean,
        secret_enc=secret_enc,
        secret_nonce=secret_nonce,
    )
    db.add(hook)
    await db.flush()
    # Pick up the server defaults (``failure_streak``, the timestamps) so the
    # caller can render the row without a round-trip of its own.
    await db.refresh(hook)
    return ConfiguredWebhook(webhook=hook, secret=secret)


async def rotate_webhook_secret(db: AsyncSession, *, merchant_id: str) -> ConfiguredWebhook:
    """Mint a new signing secret, overwriting the old one.

    There is one live key at a time and no overlap window, which is the
    opposite of the machine credential's rotation (spec §9.2, several live
    keys) — and on purpose. The overlap there exists because *the merchant*
    redeploys between issuing and revoking, and only they know when that
    finished. Here we are the sender: from the moment this returns, every
    delivery is signed with the new secret, so the merchant's window is
    "update the value, redeploy", and a second accepted secret would only
    widen what a leaked one is worth.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose secret to rotate. Must exist and have a webhook.

    Returns:
        The row and the new plaintext secret. Shown once.

    Raises:
        NotFoundError: If the merchant does not exist, or has no webhook.
    """
    hook = await get_webhook(db, merchant_id=merchant_id)
    secret = signing.new_webhook_secret()
    hook.secret_enc, hook.secret_nonce = crypto.encrypt(
        secret, purpose=crypto.PURPOSE_MERCHANT_WEBHOOK
    )
    hook.updated_at = now()
    await db.flush()
    return ConfiguredWebhook(webhook=hook, secret=secret)


async def disable_webhook(db: AsyncSession, *, merchant_id: str) -> MerchantWebhook:
    """Stop delivering to a merchant's endpoint. Idempotent.

    A timestamp, never a DELETE: the delivery log keeps pointing at a row an
    operator can read, and turning the hook back on is
    :func:`set_webhook` rather than a re-onboarding with a new secret. A
    second call leaves the first ``disabled_at`` alone — "when did we stop
    delivering" must not move because someone clicked twice.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose endpoint to disable. Must exist and have a webhook.

    Returns:
        The row, with ``disabled_at`` set.

    Raises:
        NotFoundError: If the merchant does not exist, or has no webhook.
    """
    hook = await get_webhook(db, merchant_id=merchant_id)
    if hook.disabled_at is None:
        hook.disabled_at = now()
        hook.updated_at = now()
        await db.flush()
    return hook


async def _find_webhook(db: AsyncSession, *, merchant_id: str) -> MerchantWebhook | None:
    """The merchant's webhook row, or ``None``. Unique on ``merchant_id``."""
    return (
        await db.execute(select(MerchantWebhook).where(MerchantWebhook.merchant_id == merchant_id))
    ).scalar_one_or_none()


__all__ = [
    "ConfiguredWebhook",
    "bulk_set_markup",
    "disable_webhook",
    "get_webhook",
    "list_merchants_with_balances",
    "rotate_webhook_secret",
    "set_brand_b2b",
    "set_sku_b2b",
    "set_webhook",
    "validate_webhook_url",
]
