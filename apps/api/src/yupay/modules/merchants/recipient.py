"""Who an order was for, as the reseller entered it — labelled for the cabinet.

A merchant order carries its recipient in ``OrderItem.fulfillment_data``: the
Telegram username, Steam login, player id and server the reseller sent. Those
are the reseller's own end-customer identifiers, so showing them back to that
reseller's cabinet reveals nothing they did not give us — and an operator
answering "did it reach @ivan?" needs exactly them. They still never go to a
log or a URL (``merchants.orders`` module docstring).

Only keys the product's form defines are shown, in the form's order, under the
form's own labels: an unknown key has no honest label, and the form is the
contract the reseller filled in. A Steam trade link is never shown — it carries
a token that works as a credential (``docs/security/pii-handling.md``).
"""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.catalog.models import Product, Sku
from yupay.modules.merchants.cabinet_schemas import CabinetRecipientFieldOut
from yupay.modules.orders.models import OrderItem

#: Keys never echoed back, whatever the form says.
_HIDDEN: Final = frozenset({"tradelink", "trade_link"})


def _locale_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}


def _option_label(field: dict[str, Any], value: str) -> dict[str, str] | None:
    for option in field.get("options") or []:
        if isinstance(option, dict) and str(option.get("value")) == value:
            return _locale_map(option.get("label")) or None
    return None


def recipient_fields(
    fulfillment_data: dict[str, Any] | None, required_fields: list[Any] | None
) -> list[CabinetRecipientFieldOut]:
    """Label what the reseller entered with the product's own form.

    Args:
        fulfillment_data: ``OrderItem.fulfillment_data`` — ``{key: value}``.
        required_fields: ``Product.required_fields`` as stored (raw JSON).

    Returns:
        One entry per form field that has a non-blank value, in form order.
    """
    if not fulfillment_data or not required_fields:
        return []
    out: list[CabinetRecipientFieldOut] = []
    for field in required_fields:
        if not isinstance(field, dict):
            continue
        key = field.get("key")
        if not isinstance(key, str) or key in _HIDDEN:
            continue
        value = str(fulfillment_data.get(key) or "").strip()
        if not value:
            continue
        out.append(
            CabinetRecipientFieldOut(
                key=key,
                label=_locale_map(field.get("label")),
                value=value,
                value_label=_option_label(field, value) if field.get("type") == "select" else None,
            )
        )
    return out


def recipient_summary(fields: list[CabinetRecipientFieldOut], locale: str) -> str | None:
    """One line for the Orders list: the values alone, ``"123456 · Asia"``."""
    if not fields:
        return None
    return " · ".join((f.value_label or {}).get(locale) or f.value for f in fields)


async def recipients_for_orders(
    db: AsyncSession, order_ids: list[str]
) -> dict[str, list[CabinetRecipientFieldOut]]:
    """The recipient of each order, in one query.

    Args:
        db: Session. The caller owns the transaction.
        order_ids: Orders already scoped to one merchant by the caller.

    Returns:
        ``order_id -> fields``; an order with nothing to show maps to ``[]``.
    """
    if not order_ids:
        return {}
    rows = (
        await db.execute(
            select(OrderItem.order_id, OrderItem.fulfillment_data, Product.required_fields)
            .join(Sku, Sku.id == OrderItem.sku_id)
            .join(Product, Product.id == Sku.product_id)
            .where(OrderItem.order_id.in_(order_ids))
        )
    ).all()
    return {order_id: recipient_fields(data, form) for order_id, data, form in rows}


__all__ = ["recipient_fields", "recipient_summary", "recipients_for_orders"]
