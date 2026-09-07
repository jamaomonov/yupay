"""Admin-side operations for the merchant B2B programme (M1, spec §8.3/§10).

Everything support needs to run a pilot merchant by hand that is not already
in ``service`` or ``deposit``: the balance-joined merchant list, and the
catalog B2B knobs (per-SKU markup/visibility, per-brand visibility, and the
one-action bulk markup). Reaches into ``catalog.models`` directly — the
established pattern for cross-module row access (``integrations.merchant_feed``,
``admin.service`` do the same) — and into ``wallet.models`` for the grouped
balance read, mirroring ``deposit.deposit_balance``.

The per-merchant ledger listing used to live here too; it moved to
``deposit.py`` with the rest of the deposit's reads and writes.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import String, case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.errors import NotFoundError, ValidationError
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.merchants.deposit import DEPOSIT_CURRENCY
from yupay.modules.merchants.models import Merchant
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


__all__ = [
    "bulk_set_markup",
    "list_merchants_with_balances",
    "set_brand_b2b",
    "set_sku_b2b",
]
