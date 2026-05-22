"""Cross-entity admin search service.

Composes read-only queries across ``users``, ``orders``, ``payments`` and ``catalog`` modules.
This is the first place where the ``admin`` module owns business logic — historically it only
hosted the ``require_admin`` gate. Other aggregate views (Customer 360, etc.) will live here
too. See ADR-0017.
"""

from __future__ import annotations

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from yupay.modules.admin.schemas import SearchHit, SearchOut
from yupay.modules.catalog.models import Sku
from yupay.modules.orders.models import Order
from yupay.modules.payments.models import Payment
from yupay.modules.users.models import TelegramLink, User


async def search(db: AsyncSession, *, q: str, limit: int) -> SearchOut:
    """Fan out a single query string across user/order/payment/sku sources.

    All four sub-queries run concurrently against the same session-bound engine. Each source
    contributes at most ``limit`` rows. Matching is case-insensitive (ILIKE) for text fields;
    UUID columns are matched by string prefix; ``telegram_links.tg_user_id`` matches the
    integer value when ``q`` is purely numeric.
    """

    q_norm = q.strip()
    like = f"%{q_norm}%"
    prefix_like = f"{q_norm}%"
    tg_id_int: int | None = None
    if q_norm.isdigit():
        try:
            tg_id_int = int(q_norm)
        except ValueError:  # pragma: no cover -- isdigit guarantees parse
            tg_id_int = None

    user_predicates: list[ColumnElement[bool]] = [
        User.email.ilike(like),
        User.display_name.ilike(like),
        TelegramLink.tg_username.ilike(like),
    ]
    if tg_id_int is not None:
        user_predicates.append(TelegramLink.tg_user_id == tg_id_int)

    users_stmt = (
        select(User)
        .outerjoin(TelegramLink, TelegramLink.user_id == User.id)
        .where(or_(*user_predicates))
        .order_by(User.created_at.desc())
        .limit(limit)
    )

    orders_stmt = (
        select(Order)
        .where(
            or_(
                cast(Order.id, String).ilike(prefix_like),
                Order.guest_email.ilike(like),
            )
        )
        .order_by(Order.created_at.desc())
        .limit(limit)
    )

    payments_stmt = (
        select(Payment)
        .where(
            or_(
                cast(Payment.id, String).ilike(prefix_like),
                Payment.external_id.ilike(like),
            )
        )
        .order_by(Payment.created_at.desc())
        .limit(limit)
    )

    skus_stmt = (
        select(Sku)
        .where(Sku.sku_code.ilike(like))
        .order_by(Sku.sort_order)
        .limit(limit)
    )

    # Sequential awaits: asyncpg connections aren't safe for concurrent use within the same
    # session, and per-source LIMIT keeps total cost bounded.
    users_rows = (await db.execute(users_stmt)).scalars().unique().all()
    orders_rows = (await db.execute(orders_stmt)).scalars().all()
    payments_rows = (await db.execute(payments_stmt)).scalars().all()
    skus_rows = (await db.execute(skus_stmt)).scalars().all()

    return SearchOut(
        users=[_user_hit(u) for u in users_rows],
        orders=[_order_hit(o) for o in orders_rows],
        payments=[_payment_hit(p) for p in payments_rows],
        skus=[_sku_hit(s) for s in skus_rows],
    )


def _user_hit(u: User) -> SearchHit:
    label = u.display_name or u.email or "(unnamed user)"
    sub: list[str] = []
    if u.email and label != u.email:
        sub.append(u.email)
    tg = u.telegram_link
    if tg is not None:
        if tg.tg_username:
            sub.append(f"@{tg.tg_username}")
        sub.append(f"tg:{tg.tg_user_id}")
    return SearchHit(
        type="user",
        id=u.id,
        label=label,
        sublabel=" · ".join(sub) or None,
        path=f"/users/{u.id}",
    )


def _order_hit(o: Order) -> SearchHit:
    short = o.id.split("-")[0]
    sub = f"{o.status} · {o.total_charged} {o.currency}"
    return SearchHit(
        type="order",
        id=o.id,
        label=f"Order {short}",
        sublabel=sub,
        path=f"/orders/{o.id}",
    )


def _payment_hit(p: Payment) -> SearchHit:
    short = p.id.split("-")[0]
    sub_parts = [p.provider, p.status, f"{p.amount} {p.currency}"]
    if p.external_id:
        sub_parts.append(p.external_id)
    return SearchHit(
        type="payment",
        id=p.id,
        label=f"Payment {short}",
        sublabel=" · ".join(sub_parts),
        path=f"/orders/{p.order_id}",
    )


def _sku_hit(s: Sku) -> SearchHit:
    return SearchHit(
        type="sku",
        id=s.id,
        label=s.sku_code,
        sublabel=f"price ${s.price_usd}",
        path=f"/skus/{s.id}",
    )


__all__ = ["search"]
