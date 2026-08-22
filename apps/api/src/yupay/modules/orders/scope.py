"""Which rows in ``orders`` are sales.

Since ADR-0058 the table holds two populations. A ``catalog`` row is a sale:
someone bought something and we owe them goods. A ``wallet_topup`` row is a
1:1 deposit — money moved from the customer's card to their own balance, with
no goods, no SKUs and no margin.

Counting the second as the first double-books the business: once when the
customer funds the balance, and again when they spend it on a real order. It
also pads every order count with rows that carry nothing, which quietly drags
the average order value down — the USD figures already value a deposit at
zero (they are summed per order *item*, and a deposit has none), so a deposit
adds to the denominator and never to the numerator.

Reporting reads :data:`IS_SALE`. Anything that answers "how much did we sell"
or "how many orders" wants it; anything that answers "what happened on this
order" does not, and the customer's own order list has its own copy of the
rule because it predates this module.

Deliberately not a default scope on the model: a query that must see every
row — the expiry sweep, an admin lookup by id, the payment FSM — should say
so by not asking for this, rather than by remembering to switch a global off.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement

from yupay.modules.orders.models import Order

#: A storefront sale, as opposed to a wallet deposit.
IS_SALE: ColumnElement[bool] = Order.purpose == "catalog"

__all__ = ["IS_SALE"]
