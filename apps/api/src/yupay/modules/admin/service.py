"""Cross-entity admin search service.

Composes read-only queries across ``users``, ``orders``, ``payments`` and ``catalog`` modules.
This is the first place where the ``admin`` module owns business logic — historically it only
hosted the ``require_admin`` gate. Other aggregate views (Customer 360, etc.) will live here
too. See ADR-0017.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from yupay.core.clock import now
from yupay.core.errors import ConflictError, NotFoundError
from yupay.core.ids import new_id
from yupay.modules.admin.models import AdminSavedSegment
from yupay.modules.admin.schemas import (
    CustomerBalanceOut,
    CustomerOrderSummary,
    CustomerOverviewOut,
    CustomerPaymentSummary,
    CustomerStatsOut,
    CustomerTaskSummary,
    PaymentTriageOut,
    PaymentTriageRow,
    RiskFlag,
    SavedSegmentIn,
    SearchHit,
    SearchOut,
    WebhookTriageRow,
)
from yupay.modules.catalog.models import Sku
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.orders.revenue import order_charged_usd_subq
from yupay.modules.payments.models import Payment, PaymentWebhook
from yupay.modules.users import service as users_svc
from yupay.modules.users.models import TelegramLink, User
from yupay.modules.users.schemas import UserAdminOut

# Import NORMAL_SIDE from its defining module, not the ``wallet.api`` facade:
# ``wallet.api`` pulls in ``wallet.routes`` → ``api.v1`` → ``admin``, so going
# through the facade here creates an import cycle that only bites when
# ``payments.gateways`` is imported before the app boots (e.g. in unit tests).
from yupay.modules.wallet.models import WalletAccount, WalletPosting
from yupay.modules.wallet.service import NORMAL_SIDE


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

    skus_stmt = select(Sku).where(Sku.sku_code.ilike(like)).order_by(Sku.sort_order).limit(limit)

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
        path=f"/customers/{u.id}",
    )


def _order_hit(o: Order) -> SearchHit:
    short = o.id.split("-")[0]
    return SearchHit(
        type="order",
        id=o.id,
        label=f"Order {short}",
        status=o.status,
        amount=o.total_charged,
        currency=o.currency,
        path=f"/orders/{o.id}",
    )


def _payment_hit(p: Payment) -> SearchHit:
    short = p.id.split("-")[0]
    # ``sublabel`` keeps only what doesn't fit status/amount — provider and
    # (when present) the upstream external id. Status and amount go through
    # their own fields so the admin SPA can localize/format them itself
    # (round-2 fix — raw status + un-grouped amount used to leak straight
    # into this string; see AGENTS.md).
    sublabel = f"{p.provider} · {p.external_id}" if p.external_id else p.provider
    return SearchHit(
        type="payment",
        id=p.id,
        label=f"Payment {short}",
        sublabel=sublabel,
        status=p.status,
        amount=p.amount,
        currency=p.currency,
        path=f"/orders/{p.order_id}",
    )


def _sku_hit(s: Sku) -> SearchHit:
    return SearchHit(
        type="sku",
        id=s.id,
        label=s.sku_code,
        amount=s.price_usd,
        currency="USD",
        path=f"/skus/{s.id}",
    )


# ---------- Customer 360 overview ----------

_OPEN_TASK_STATUSES: tuple[str, ...] = ("pending", "in_progress", "failed")
_DELIVERED_STATUSES: tuple[str, ...] = ("delivered", "fulfilled")
_FRESH_ACCOUNT_DAYS = 7
_FAILED_PAYMENTS_THRESHOLD = 3
_DEFAULT_LIMIT = 10


async def get_customer_overview(
    db: AsyncSession,
    *,
    user_id: str,
    limit: int = _DEFAULT_LIMIT,
) -> CustomerOverviewOut:
    """Aggregate read-only view for the admin SPA's /customers/{user_id} page.

    Composes existing module reads. Bounded SQL: a fixed handful of queries
    regardless of how many wallet accounts the user has — balances are computed in
    a single GROUP BY query keyed on the user's accounts.
    """

    user = await users_svc.get_user_admin(db, user_id)  # 404 if missing.

    order_id_subq = select(Order.id).where(Order.user_id == user_id).scalar_subquery()

    recent_orders = await _fetch_recent_orders(db, user_id=user_id, limit=limit)
    recent_payments = await _fetch_recent_payments(db, order_id_subq=order_id_subq, limit=limit)
    open_tasks = await _fetch_open_fulfillment_tasks(db, order_id_subq=order_id_subq, limit=limit)
    wallet_balances = await _fetch_wallet_balances(db, user_id=user_id)
    stats = await _fetch_customer_stats(db, user_id=user_id, order_id_subq=order_id_subq)

    risk_flags = _compute_risk_flags(user=user, failed_payments=stats.failed_payments)

    return CustomerOverviewOut(
        user=UserAdminOut.model_validate(user),
        stats=stats,
        recent_orders=recent_orders,
        recent_payments=recent_payments,
        open_fulfillment_tasks=open_tasks,
        wallet_balances=wallet_balances,
        risk_flags=risk_flags,
    )


async def _fetch_recent_orders(
    db: AsyncSession, *, user_id: str, limit: int
) -> list[CustomerOrderSummary]:
    items_count_col = (
        select(func.count(OrderItem.id))
        .where(OrderItem.order_id == Order.id)
        .correlate(Order)
        .scalar_subquery()
    )
    stmt = (
        select(
            Order.id,
            Order.status,
            Order.currency,
            Order.total_charged,
            items_count_col.label("items_count"),
            Order.created_at,
            Order.delivered_at,
        )
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).mappings().all()
    return [CustomerOrderSummary.model_validate(dict(r)) for r in rows]


async def _fetch_recent_payments(
    db: AsyncSession, *, order_id_subq: object, limit: int
) -> list[CustomerPaymentSummary]:
    stmt = (
        select(Payment)
        .where(Payment.order_id.in_(order_id_subq))  # type: ignore[arg-type]
        .order_by(Payment.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [CustomerPaymentSummary.model_validate(p) for p in rows]


async def _fetch_open_fulfillment_tasks(
    db: AsyncSession, *, order_id_subq: object, limit: int
) -> list[CustomerTaskSummary]:
    stmt = (
        select(FulfillmentTask)
        .where(
            FulfillmentTask.order_id.in_(order_id_subq),  # type: ignore[arg-type]
            FulfillmentTask.status.in_(_OPEN_TASK_STATUSES),
        )
        .order_by(FulfillmentTask.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [CustomerTaskSummary.model_validate(t) for t in rows]


async def _fetch_wallet_balances(db: AsyncSession, *, user_id: str) -> list[CustomerBalanceOut]:
    """One query per balance set, no matter how many accounts.

    Each posting is signed according to its account's NORMAL_SIDE (debit-normal vs
    credit-normal) so the SUM is the on-screen balance directly.
    """
    case_branches = [
        ((WalletAccount.kind == kind) & (WalletPosting.direction == ns), WalletPosting.amount)
        for kind, ns in NORMAL_SIDE.items()
    ]
    signed_expr = case(*case_branches, else_=-WalletPosting.amount)
    stmt = (
        select(
            WalletAccount.id,
            WalletAccount.kind,
            WalletAccount.currency,
            func.coalesce(func.sum(signed_expr), Decimal("0")).label("balance"),
        )
        .select_from(WalletAccount)
        .outerjoin(WalletPosting, WalletPosting.account_id == WalletAccount.id)
        .where(WalletAccount.owner_type == "user", WalletAccount.owner_id == user_id)
        .group_by(WalletAccount.id, WalletAccount.kind, WalletAccount.currency)
        .order_by(WalletAccount.kind, WalletAccount.currency)
    )
    rows = (await db.execute(stmt)).all()
    return [
        CustomerBalanceOut(
            account_id=row[0],
            kind=row[1],
            currency=row[2],
            balance=Decimal(row[3] or 0),
        )
        for row in rows
    ]


async def _fetch_customer_stats(
    db: AsyncSession, *, user_id: str, order_id_subq: object
) -> CustomerStatsOut:
    # Spend is the *charged* value, not `Order.total_usd`: on a Steam top-up
    # the latter is the face value the customer picked ($10 of credit), so
    # summing it reports a buyer who paid ~$11.30 as having spent $10 — see
    # `orders.revenue`. Joined as a pre-grouped subquery so the two counts
    # beside it keep counting orders rather than order lines.
    gross = order_charged_usd_subq()
    orders_stmt = (
        select(
            func.count(Order.id),
            func.count(case((Order.status.in_(_DELIVERED_STATUSES), 1))),
            func.coalesce(
                func.sum(case((Order.status.in_(_DELIVERED_STATUSES), gross.c.charged_usd))),
                Decimal("0"),
            ),
        )
        .select_from(Order)
        .join(gross, gross.c.order_id == Order.id, isouter=True)
        .where(Order.user_id == user_id)
    )
    total_orders, delivered_orders, total_spent = (await db.execute(orders_stmt)).one()

    failed_stmt = select(func.count(Payment.id)).where(
        Payment.order_id.in_(order_id_subq),  # type: ignore[arg-type]
        Payment.status == "failed",
    )
    failed_payments = (await db.execute(failed_stmt)).scalar_one()

    return CustomerStatsOut(
        total_orders=int(total_orders or 0),
        delivered_orders=int(delivered_orders or 0),
        total_spent_usd=Decimal(total_spent or 0),
        failed_payments=int(failed_payments or 0),
    )


# ---------- Payments Triage ----------

_DEFAULT_STUCK_AFTER_MINUTES = 30
_TRIAGE_PER_BUCKET = 100


async def triage_payments(
    db: AsyncSession, *, stuck_after_minutes: int = _DEFAULT_STUCK_AFTER_MINUTES
) -> PaymentTriageOut:
    """Two focused buckets for the payment triage screen.

    Stuck-pending = ``payments.status='pending'`` older than ``stuck_after_minutes``.
    Failed-webhooks = webhooks with ``signature_ok=False`` or ``processed_at IS NULL``.
    Each bucket is capped at :data:`_TRIAGE_PER_BUCKET` rows; a working day's queue
    that doesn't fit shouldn't be solved with a bigger LIMIT.
    """
    moment = now()
    cutoff = moment - timedelta(minutes=stuck_after_minutes)

    stuck_stmt = (
        select(
            Payment.id,
            Payment.order_id,
            Order.user_id,
            Order.guest_email,
            Payment.provider,
            Payment.status,
            Payment.amount,
            Payment.currency,
            Payment.created_at,
        )
        .join(Order, Order.id == Payment.order_id)
        .where(Payment.status == "pending", Payment.created_at < cutoff)
        .order_by(Payment.created_at.asc())  # oldest first — they're the most urgent
        .limit(_TRIAGE_PER_BUCKET)
    )
    stuck_rows = (await db.execute(stuck_stmt)).all()
    stuck = [
        PaymentTriageRow(
            id=row[0],
            order_id=row[1],
            user_id=row[2],
            guest_email=row[3],
            provider=row[4],
            status=row[5],
            amount=row[6],
            currency=row[7],
            created_at=row[8],
            waiting_minutes=max(0, int((moment - row[8]).total_seconds() // 60)),
        )
        for row in stuck_rows
    ]

    webhook_stmt = (
        select(PaymentWebhook)
        .where((PaymentWebhook.signature_ok.is_(False)) | (PaymentWebhook.processed_at.is_(None)))
        .order_by(PaymentWebhook.received_at.desc())
        .limit(_TRIAGE_PER_BUCKET)
    )
    webhook_rows = (await db.execute(webhook_stmt)).scalars().all()
    failed_webhooks = [WebhookTriageRow.model_validate(w) for w in webhook_rows]

    return PaymentTriageOut(
        threshold_minutes=stuck_after_minutes,
        stuck_pending=stuck,
        failed_webhooks=failed_webhooks,
    )


def _compute_risk_flags(*, user: User, failed_payments: int) -> list[RiskFlag]:
    flags: list[RiskFlag] = []
    if not user.email:
        flags.append("no_email")
    if user.telegram_link is None:
        flags.append("no_telegram")
    if (now() - user.created_at) < timedelta(days=_FRESH_ACCOUNT_DAYS):
        flags.append("fresh_account")
    if failed_payments > _FAILED_PAYMENTS_THRESHOLD:
        flags.append("many_failed_payments")
    return flags


# ---------- Saved segments ----------


async def create_saved_segment(
    db: AsyncSession, *, owner_user_id: str, body: SavedSegmentIn
) -> AdminSavedSegment:
    """Persist a per-owner bookmark. Name is unique per owner — duplicates 409."""
    row = AdminSavedSegment(
        id=new_id(),
        owner_user_id=owner_user_id,
        name=body.name,
        path=body.path,
        params=body.params,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            "saved segment with this name already exists",
            extra={"name": body.name},
        ) from exc
    await db.commit()
    return row


async def list_saved_segments(db: AsyncSession, *, owner_user_id: str) -> list[AdminSavedSegment]:
    stmt = (
        select(AdminSavedSegment)
        .where(AdminSavedSegment.owner_user_id == owner_user_id)
        .order_by(AdminSavedSegment.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def delete_saved_segment(db: AsyncSession, *, owner_user_id: str, segment_id: str) -> None:
    """Remove the bookmark. 404 if not found OR not owned — never leak existence
    of another admin's segment id."""
    row = (
        await db.execute(
            select(AdminSavedSegment).where(
                AdminSavedSegment.id == segment_id,
                AdminSavedSegment.owner_user_id == owner_user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("saved segment not found")
    await db.delete(row)
    await db.commit()


__all__ = [
    "create_saved_segment",
    "delete_saved_segment",
    "get_customer_overview",
    "list_saved_segments",
    "search",
    "triage_payments",
]
