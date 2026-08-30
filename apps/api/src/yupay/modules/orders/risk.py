"""Whether a paid order may be fulfilled automatically. See ADR-0047, ADR-0062.

Kept apart from both ``payments`` and ``fulfillment``: the decision is neither
about taking money nor about delivering goods.

Two kinds of rule live here. Rule 1 looks at this order alone (its amount
against a jittered threshold). Rules 2-4 look at this order's identity —
buyer, IP, device, delivery target, drawn from ``order_evidence`` — against
its recent paid siblings in a trailing 7-day window, to catch the pattern a
single order can never show: many small orders instead of one large one, a
burst of orders in a day, or one IP paying for several "different" buyers.
Rule 5 adds the order's own browser-reported timezone against the storefront's
home markets, but only for guests on cash-equivalent brands.

Nothing here blocks a sale. Payment already happened; the only question is
whether a human looks before the goods leave, and holding is reversible in one
click while an issued game code is not.
"""

from __future__ import annotations

import contextlib
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.evidence.models import OrderEvidence
from yupay.modules.orders.models import Order, OrderEvent, OrderItem

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger("yupay.orders.risk")

#: Written to ``order_events`` and shown in the alert.
REASON_LARGE_AMOUNT = "amount_at_or_above_threshold"

#: The acquirer debited the customer after we had already written the order
#: off as expired. The sale is real, but it was priced and stocked ten minutes
#: ago and nobody expected it any more, so a human decides whether to deliver
#: or refund.
REASON_PAID_AFTER_EXPIRY = "paid_after_order_expired"

#: Orders sharing an identity (buyer, IP, device, or delivery target) whose
#: combined total over a trailing window reaches `risk_sum_24h_usd` or
#: `risk_sum_7d_usd`. Many small orders rather than one large one.
REASON_ROLLING_SUM = "identity_rolling_sum_exceeded"

#: Orders sharing an identity whose count over the trailing 24h reaches
#: `risk_velocity_24h` — a burst of many cheap orders is itself a signal,
#: regardless of amount.
REASON_VELOCITY = "identity_velocity_exceeded"

#: One IP or device paying for several distinct buyer identities within the
#: trailing 7 days — reaches `risk_distinct_buyers_7d`. Matched narrowly (IP
#: or device only, not buyer or delivery target) because those two are what a
#: single physical actor cannot fake cheaply; buyer and target are exactly
#: the things a resale ring rotates on purpose.
REASON_SHARED_IDENTITY = "identity_shared_across_buyers"

#: A guest checkout for a cash-equivalent brand (`risk_liquid_brands`) whose
#: browser reports a timezone outside the storefront's home markets
#: (`risk_home_timezones`). Weak on its own — a traveller is not a fraudster —
#: which is why it is the last rule to fire and only fires alongside the
#: other two conditions.
REASON_GEO_MISMATCH = "guest_liquid_brand_foreign_timezone"


#: reason -> (alert title, what the operator should do). Kept beside the
#: reasons rather than inside ``hold_for_review`` so adding a rule without
#: wording it is a visible omission: the old text said "крупный заказ"
#: whatever the reason was, and the second rule made it a lie.
HOLD_ALERT_TEXT: dict[str, tuple[str, str]] = {
    REASON_LARGE_AMOUNT: (
        "🔍 Крупный заказ — на проверке",
        "Оплачен, выдача НЕ запущена. Проверь плательщика, затем выдай или верни деньги.",
    ),
    REASON_PAID_AFTER_EXPIRY: (
        "🔍 Оплата пришла на истёкший заказ",
        "Заказ уже был закрыт, когда пришли деньги. Выдача НЕ запущена — "
        "реши, выдавать или вернуть. Для пополнения кошелька: зачислить вручную "
        "или вернуть, см. runbook paid-after-expiry.",
    ),
    REASON_ROLLING_SUM: (
        "🔍 Серия заказов — на проверке",
        "Сумма связанных заказов за окно превысила лимит. Смотри всю серию по "
        "покупателю/IP в админке, не только этот заказ: выдай или верни по каждому.",
    ),
    REASON_VELOCITY: (
        "🔍 Слишком частые заказы — на проверке",
        "Больше N оплаченных заказов одной личности за сутки. Проверь серию целиком.",
    ),
    REASON_SHARED_IDENTITY: (
        "🔍 Один источник — разные покупатели",
        "С одного IP/устройства платят несколько «разных» покупателей. Найди в "
        "админке все заказы этой группы, прежде чем что-то выдавать: выпуск "
        "одного заказа из связки обесценивает правило.",
    ),
    REASON_GEO_MISMATCH: (
        "🔍 Гость из чужой таймзоны на ликвидном товаре",
        "Roblox/Stars, гость, таймзона вне домашнего списка. Классический "
        "профиль кардера — но им может оказаться и честный покупатель в "
        "поездке: посмотри и реши.",
    ),
}


def _effective_threshold(order_id: str, cfg: Settings) -> Decimal:
    """Rule 1's threshold for this order — jittered so probing finds a band,
    not an edge. Deterministic per order id: retries and tests are stable."""
    base = cfg.manual_review_threshold_usd
    if not cfg.risk_jitter or base <= 0:
        return base
    u = int.from_bytes(hashlib.sha256(order_id.encode()).digest()[:8], "big") / 2**64
    return base * (Decimal("0.6") + Decimal("0.4") * Decimal(str(u)))


def _amount_reason(order: Order, cfg: Settings) -> str | None:
    """Rule 1: is this single order, on its own, big enough to hold?"""
    threshold = _effective_threshold(order.id, cfg)
    if cfg.manual_review_threshold_usd > 0 and order.total_usd >= threshold:
        return REASON_LARGE_AMOUNT
    return None


@dataclass(frozen=True)
class WindowOrder:
    """One paid order's identity fingerprint, for the window rules (rules 2-3).

    Built once by ``_gather`` and never touches the database again — the window
    rules only compare these dataclasses against each other, which is what makes
    them pure and unit-testable without a session.
    """

    id: str
    paid_at: datetime
    total_usd: Decimal
    buyer: str | None  # user_id or guest_email
    ip: str | None
    device: str | None
    targets: frozenset[str]


@dataclass(frozen=True)
class GeoContext:
    """What rule 5 (geo mismatch) needs about the current order alone.

    Unlike ``WindowOrder`` this never looks at other orders — it is the
    current order's own guest/signed-in status, which brands its items touch,
    and its evidence row's reported timezone.
    """

    is_guest: bool
    brand_slugs: frozenset[str]
    timezone: str | None


def _csv(value: str) -> frozenset[str]:
    """Parse a `risk_liquid_brands`/`risk_home_timezones`-shaped CSV setting.

    Lowercased and trimmed so an operator's ``RISK_LIQUID_BRANDS=Roblox, Steam``
    matches the data it is compared against; empty segments (a trailing comma,
    a doubled comma, an all-blank setting) are dropped rather than becoming a
    surprise membership test against ``""``.
    """
    return frozenset(v for raw in value.split(",") if (v := raw.strip().lower()))


def _targets_from(fulfillment_data: dict[str, Any]) -> frozenset[str]:
    """Delivery targets inside one order item's ``fulfillment_data``.

    Values only (a Roblox username, a Stars ``@handle``) — the keys are field
    names like ``"username"``, not identities. Lowercased, ``@``-stripped and
    whitespace-trimmed so ``@durov`` and ``" Durov "`` link to the same
    account; empties are skipped.
    """
    targets: set[str] = set()
    for value in fulfillment_data.values():
        if not isinstance(value, str):
            continue
        cleaned = value.strip().lower().lstrip("@")
        if cleaned:
            targets.add(cleaned)
    return frozenset(targets)


def _shares_key(a: WindowOrder, b: WindowOrder) -> bool:
    """Whether two orders look like the same actor: buyer, IP, device, or target."""
    return (
        (a.buyer is not None and a.buyer == b.buyer)
        or (a.ip is not None and a.ip == b.ip)
        or (a.device is not None and a.device == b.device)
        or bool(a.targets & b.targets)
    )


def _shares_ip_or_device(a: WindowOrder, b: WindowOrder) -> bool:
    """Same physical actor: IP or device, not buyer or delivery target.

    Narrower than ``_shares_key`` on purpose — rule 4 asks "how many different
    buyers used this one IP/device", and buyer or target would beg the
    question: a resale ring's whole method is a different buyer identity (and
    often a different delivery target) on every order.
    """
    return (a.ip is not None and a.ip == b.ip) or (a.device is not None and a.device == b.device)


def _window_reason(current: WindowOrder, recent: list[WindowOrder], cfg: Settings) -> str | None:
    """Rules 2-4: rolling sum, velocity, and shared identity, across orders
    sharing an identity.

    Pure — no clock reads. Every comparison is against ``current.paid_at``, not
    the wall clock, which is what makes this deterministic and testable without
    freezing time.
    """
    linked24 = [
        r
        for r in recent
        if _shares_key(current, r) and r.paid_at >= current.paid_at - timedelta(hours=24)
    ]
    linked7d = [r for r in recent if _shares_key(current, r)]
    if (
        cfg.risk_sum_24h_usd > 0
        and current.total_usd + sum((r.total_usd for r in linked24), Decimal("0"))
        >= cfg.risk_sum_24h_usd
    ):
        return REASON_ROLLING_SUM
    if (
        cfg.risk_sum_7d_usd > 0
        and current.total_usd + sum((r.total_usd for r in linked7d), Decimal("0"))
        >= cfg.risk_sum_7d_usd
    ):
        return REASON_ROLLING_SUM
    if cfg.risk_velocity_24h > 0 and len(linked24) >= cfg.risk_velocity_24h:
        return REASON_VELOCITY
    if cfg.risk_distinct_buyers_7d > 0:
        linked_by_ip_or_device = [r for r in linked7d if _shares_ip_or_device(current, r)]
        buyers = {r.buyer for r in linked_by_ip_or_device if r.buyer is not None}
        if current.buyer is not None:
            buyers.add(current.buyer)
        if len(buyers) >= cfg.risk_distinct_buyers_7d:
            return REASON_SHARED_IDENTITY
    return None


def _geo_reason(
    order_is_guest: bool,
    item_brand_slugs: frozenset[str],
    tz: str | None,
    cfg: Settings,
) -> str | None:
    """Rule 5: a guest buying a liquid brand from outside the home timezones.

    Weak evidence taken alone — a genuine customer travels — so it only fires
    when all three conditions line up: not signed in, the order touches a
    cash-equivalent brand, and the browser reported a timezone that is neither
    unknown nor one of ours. An empty ``risk_liquid_brands`` or
    ``risk_home_timezones`` disables the rule entirely rather than treating
    "nothing configured" as "everything foreign".
    """
    if not order_is_guest:
        return None
    liquid = _csv(cfg.risk_liquid_brands)
    if not liquid or not (item_brand_slugs & liquid):
        return None
    if tz is None:
        return None
    home = _csv(cfg.risk_home_timezones)
    if not home:
        return None
    if tz.strip().lower() not in home:
        return REASON_GEO_MISMATCH
    return None


async def _gather(
    db: AsyncSession, order: Order
) -> tuple[WindowOrder, list[WindowOrder], GeoContext]:
    """Assemble the current order's identity fingerprint, its recent paid
    siblings, and the geo context for rule 5.

    Two queries, matched together in Python rather than one joined query — the
    trailing-7-day window holds at most a few hundred paid orders at current
    volume (the assumption that makes a Python-side scan honest; revisit if
    traffic outgrows it), so the extra round trip buys a query each side can
    read on its own.

    Query A pulls every other order paid in the trailing 7 days (catalog orders
    only — a wallet top-up has no delivery target and cannot be linked by one).
    Query B pulls ``fulfillment_data`` for those orders plus this one, to derive
    delivery targets. The current order's own evidence row is fetched
    separately by ``order_id``, together with ``client_hints`` for the
    reported timezone — reusing the row rather than a second query. Query C
    joins the current order's own items through to their brands, for rule 5's
    "liquid brand" check; only the current order, because only its guest
    status and its items are relevant to that rule.

    Never raises: a broken risk query must degrade to the amount rule alone,
    not block a sale. On any failure this returns the current order with no
    identity, an empty recent list, and a ``GeoContext`` that cannot fire rule
    5 — ``is_guest=False`` alone is enough for that, but every field is left
    neutral so a partial read of this function's changes can't accidentally
    make it claim something it doesn't know.
    """
    try:
        window_start = now() - timedelta(days=7)
        rows = (
            await db.execute(
                select(
                    Order.id,
                    Order.paid_at,
                    Order.total_usd,
                    Order.user_id,
                    Order.guest_email,
                    OrderEvidence.ip,
                    OrderEvidence.device_hash,
                )
                .select_from(Order)
                .outerjoin(OrderEvidence, OrderEvidence.order_id == Order.id)
                .where(
                    Order.paid_at.is_not(None),
                    Order.paid_at >= window_start,
                    Order.id != order.id,
                    Order.purpose == "catalog",
                )
            )
        ).all()

        current_evidence_row = (
            await db.execute(
                select(
                    OrderEvidence.ip, OrderEvidence.device_hash, OrderEvidence.client_hints
                ).where(OrderEvidence.order_id == order.id)
            )
        ).first()
        raw_tz = current_evidence_row[2].get("timezone") if current_evidence_row else None
        timezone = raw_tz if isinstance(raw_tz, str) else None

        brand_slugs = frozenset(
            (
                await db.execute(
                    select(Brand.slug)
                    .select_from(OrderItem)
                    .join(Sku, Sku.id == OrderItem.sku_id)
                    .join(Product, Product.id == Sku.product_id)
                    .join(Brand, Brand.id == Product.brand_id)
                    .where(OrderItem.order_id == order.id)
                )
            )
            .scalars()
            .all()
        )

        item_rows = (
            await db.execute(
                select(OrderItem.order_id, OrderItem.fulfillment_data).where(
                    OrderItem.order_id.in_([row[0] for row in rows] + [order.id])
                )
            )
        ).all()
        targets_by_order: dict[str, set[str]] = {}
        for order_id, fulfillment_data in item_rows:
            targets_by_order.setdefault(order_id, set()).update(_targets_from(fulfillment_data))

        recent = [
            WindowOrder(
                id=row[0],
                paid_at=row[1],
                total_usd=row[2],
                buyer=row[3] or row[4],
                ip=row[5],
                device=row[6],
                targets=frozenset(targets_by_order.get(row[0], set())),
            )
            for row in rows
        ]
        current = WindowOrder(
            id=order.id,
            # `order.paid_at` may still be None here: the gate runs at payment
            # success and `mark_paid` stamps it just before this call, but a
            # defensive fallback beats an AttributeError in a money path.
            paid_at=order.paid_at or now(),
            total_usd=order.total_usd,
            buyer=order.user_id or order.guest_email,
            ip=current_evidence_row[0] if current_evidence_row else None,
            device=current_evidence_row[1] if current_evidence_row else None,
            targets=frozenset(targets_by_order.get(order.id, set())),
        )
        geo = GeoContext(
            is_guest=order.user_id is None,
            brand_slugs=brand_slugs,
            timezone=timezone,
        )
    except Exception:
        log.exception("orders.risk.gather_failed", order_id=order.id)
        return (
            WindowOrder(
                id=order.id,
                paid_at=order.paid_at or now(),
                total_usd=order.total_usd,
                buyer=order.user_id or order.guest_email,
                ip=None,
                device=None,
                targets=frozenset(),
            ),
            [],
            GeoContext(is_guest=False, brand_slugs=frozenset(), timezone=None),
        )
    else:
        return current, recent, geo


async def review_reason(
    db: AsyncSession,
    order: Order,
    *,
    settings: Settings | None = None,
) -> str | None:
    """Why this order must not be fulfilled automatically, or ``None``.

    Returns a reason string rather than a bool so the event log and the alert
    can say which rule fired — with one rule that is pedantic, with five it is
    the difference between a useful log line and a shrug.

    Rule order is amount, rolling sum, velocity, shared identity, geo — each
    a stronger claim resting on more context than the last, so the cheapest
    and most confident check runs first. Rule 1 (amount) runs first and
    short-circuits: a single order already over threshold does not need the
    window gather. Rules 2-5 (rolling sum, velocity, shared identity, geo)
    never raise on their own — a failed gather is logged and degrades to rule
    1's result alone, because a broken risk query must not stop all sales.
    """
    cfg = settings or get_settings()
    amount = _amount_reason(order, cfg)
    if amount is not None:
        return amount
    current, recent, geo = await _gather(db, order)
    window = _window_reason(current, recent, cfg)
    if window is not None:
        return window
    return _geo_reason(geo.is_guest, geo.brand_slugs, geo.timezone, cfg)


async def hold_for_review(
    db: AsyncSession,
    *,
    order: Order,
    reason: str,
    detail: dict[str, int] | None = None,
) -> None:
    """Record the hold and tell an operator. Never raises.

    The order keeps status ``paid``: the customer's view stays "processing",
    which is what it honestly is, and no new state has to be taught to the
    storefront, the mini app and the FSM. Fulfilment simply never starts, and
    ``fulfillment.start_for_order`` accepts a ``paid`` order, so releasing the
    hold later is the same call that would have run now.

    ``detail`` is merged into the event payload when given. Counts only
    (``{"linked_orders_24h": 5}``) — never identities: the payload lands in an
    audit log an operator reads, not a place for another buyer's IP or email.
    """
    payload: dict[str, Any] = {"reason": reason, "total_usd": str(order.total_usd)}
    if detail:
        payload.update(detail)
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind="order.held_for_review",
            payload=payload,
            actor="risk",
        )
    )
    log.warning("orders.held_for_review", order_id=order.id, reason=reason)

    # Pre-arm the stuck-order watchdog's per-order key so its first reminder
    # lands one repeat window from now instead of 15 minutes from now. Without
    # this a held order produces two alerts in quarter of an hour, and an alert
    # channel that repeats itself is one that stops being read.
    with contextlib.suppress(Exception):
        cfg = get_settings()
        await get_redis().set(
            f"alert:stuck_order:{order.id}",
            "1",
            ex=cfg.stuck_order_alert_repeat_hours * 3600,
            nx=True,
        )

    from yupay.modules.notifications.alerts import send_admin_alert

    charged = f"{order.total_charged:,.0f}".replace(",", " ")
    title, what_to_do = HOLD_ALERT_TEXT.get(reason, HOLD_ALERT_TEXT[REASON_LARGE_AMOUNT])
    with contextlib.suppress(Exception):
        await send_admin_alert(
            f"<b>{title}</b>\n"
            f"Заказ: <code>{order.id[:8]}…</code>\n"
            f"Сумма: <b>{charged} {order.currency}</b> (${order.total_usd})\n"
            f"<i>{what_to_do}</i>",
            kind="order_held_for_review",
        )


__all__ = [
    "HOLD_ALERT_TEXT",
    "REASON_GEO_MISMATCH",
    "REASON_LARGE_AMOUNT",
    "REASON_PAID_AFTER_EXPIRY",
    "REASON_ROLLING_SUM",
    "REASON_SHARED_IDENTITY",
    "REASON_VELOCITY",
    "GeoContext",
    "WindowOrder",
    "hold_for_review",
    "review_reason",
]
