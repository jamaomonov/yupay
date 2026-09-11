"""Predicate for ``GET /admin/orders?q=``.

Kept out of ``orders.service`` so the list query can grow without pushing that
file further past the length cap, and so the merchant table can be imported
here without closing the ``orders`` ↔ ``merchants`` cycle at module load.

Every historical branch stays index-backed (migration 0039). The name / email
/ catalog / merchant branches need the trigram indexes in migration 0074;
without them they still return the right rows, they just seq-scan.
"""

from __future__ import annotations

import uuid
from contextlib import suppress

from sqlalchemy import Text, cast, exists, func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from yupay.modules.catalog.models import BrandTranslation, Product, ProductTranslation, Sku
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.users.models import User

_MIN_SEARCH_LEN = 3


def admin_search_clause(q: str) -> ColumnElement[bool] | None:
    """Build the ``q`` predicate for the admin order list, or None if unusable.

    - a full UUID hits the ``orders`` primary key or ``ix_orders_user_created``;
    - a string containing ``@`` matches guest email (``ix_orders_guest_email_trgm``)
      and the owner's ``users.email``;
    - anything else is an id prefix (``ix_orders_id_prefix``) **or** a substring
      of the owner's name/email, a catalog brand/product name, or a merchant
      title.

    Shorter than three characters is rejected rather than run: a one-character
    prefix matches a sixteenth of the table and is never what someone meant.
    """
    term = q.strip()
    if len(term) < _MIN_SEARCH_LEN:
        return None
    with suppress(ValueError):
        canonical = str(uuid.UUID(term))
        return or_(Order.id == canonical, Order.user_id == canonical)
    needle = f"%{term.lower()}%"
    if "@" in term:
        # Spelled to match ``ix_orders_guest_email_trgm`` exactly: an expression
        # index is only used by a predicate of the same shape, so ``ILIKE`` on
        # the CITEXT column would quietly fall back to a sequential scan.
        return or_(
            func.lower(cast(Order.guest_email, Text)).like(f"%{term.lower()}%"),
            _user_email_exists(needle),
        )
    return or_(
        cast(Order.id, Text).like(f"{term.lower()}%"),
        _user_identity_exists(needle),
        _catalog_name_exists(needle),
        _merchant_title_exists(needle),
    )


def _user_email_exists(needle: str) -> ColumnElement[bool]:
    return exists(
        select(1)
        .select_from(User)
        .where(
            User.id == Order.user_id,
            func.lower(cast(User.email, Text)).like(needle),
        )
    )


def _user_identity_exists(needle: str) -> ColumnElement[bool]:
    return exists(
        select(1)
        .select_from(User)
        .where(
            User.id == Order.user_id,
            or_(
                func.lower(cast(User.display_name, Text)).like(needle),
                func.lower(cast(User.email, Text)).like(needle),
            ),
        )
    )


def _catalog_name_exists(needle: str) -> ColumnElement[bool]:
    return exists(
        select(1)
        .select_from(OrderItem)
        .join(Sku, Sku.id == OrderItem.sku_id)
        .join(Product, Product.id == Sku.product_id)
        .where(
            OrderItem.order_id == Order.id,
            or_(
                exists(
                    select(1)
                    .select_from(ProductTranslation)
                    .where(
                        ProductTranslation.product_id == Product.id,
                        func.lower(ProductTranslation.name).like(needle),
                    )
                ),
                exists(
                    select(1)
                    .select_from(BrandTranslation)
                    .where(
                        BrandTranslation.brand_id == Product.brand_id,
                        func.lower(BrandTranslation.name).like(needle),
                    )
                ),
            ),
        )
    )


def _merchant_title_exists(needle: str) -> ColumnElement[bool]:
    # Function-local: ``merchants.models`` must not be imported at module
    # load from ``orders`` (see ``merchant_titles_for``). Compiling the
    # clause still needs the mapped class, so the import happens when the
    # search actually runs.
    from yupay.modules.merchants.models import Merchant

    return exists(
        select(1)
        .select_from(Merchant)
        .where(
            Merchant.id == Order.merchant_id,
            func.lower(Merchant.title).like(needle),
        )
    )


__all__ = ["admin_search_clause"]
