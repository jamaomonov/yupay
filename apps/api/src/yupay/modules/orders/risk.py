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

``precharge_veto`` (ADR-0063) is the one exception: it runs *before* the
charge, at the acquirers' own pre-charge stage, and can refuse the payment
outright for a guest or fresh account whose evidence puts them outside the
storefront's home countries/timezones. Deliberately brand-agnostic, unlike
rule 5 above, and built on a pure decision core (``_veto_decision``) so its
two enforcement points (the acquirer stage, and order creation) can never
drift from each other — see that function's docstring for the actual rule.

A hold from any rule above is reversible by an operator, but not indefinitely:
``auto_refund_expired_holds`` (also ADR-0063) refunds a still-held order once
``risk_hold_auto_refund_hours`` has passed with nobody releasing or refunding
it by hand, so the alert this module already sends has an actual deadline
behind it instead of trusting it to be seen — where the gateway actually
supports a merchant-initiated refund (``_AUTO_REFUNDABLE_PROVIDERS``). Payme,
Click, and Uzum do not, so a held order paid through one of those is
escalated to a human once instead of being retried forever.
"""

from __future__ import annotations

import contextlib
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, NamedTuple

from sqlalchemy import Text, bindparam, func, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.core.money import format_amount
from yupay.core.redis import get_redis
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.evidence.models import OrderEvidence
from yupay.modules.orders.models import Order, OrderEvent, OrderItem
from yupay.modules.payments.models import Payment

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

#: `order_evidence.ip_country` (Cloudflare's edge-resolved country) is present
#: and outside `risk_home_countries` for a guest or fresh account. Refused
#: before the charge — see `precharge_veto`, ADR-0063.
#: A liquid-brand order (`risk_liquid_brands`) at or above the LOWER
#: `risk_liquid_review_threshold_usd`. Click's rule 2 (2026-09-02): the
#: fraud waves cash out through Stars/Roblox at the largest amount the shop
#: allows, so the cash-equivalents get a tighter bar than the global one.
REASON_LIQUID_AMOUNT = "liquid_amount_at_or_above_threshold"

#: An identity first seen within `risk_new_buyer_age_days` exceeded the
#: new-buyer caps (`risk_new_buyer_velocity_24h` orders or
#: `risk_new_buyer_sum_24h_usd` dollars per rolling day). Click's rule 3:
#: a customer with history keeps automatic delivery; a fresh identity gets
#: three small purchases and then a human.
REASON_NEW_BUYER = "new_buyer_over_limits"

VETO_FOREIGN_COUNTRY = "precharge_foreign_country"

#: Same refusal, from the weaker fallback signal: no `ip_country` on the
#: evidence row (header missing, or pre-toggle order), but the browser's own
#: reported timezone is outside `risk_home_timezones`.
VETO_FOREIGN_TIMEZONE = "precharge_foreign_timezone"

#: A `hold_for_review` order sat past `risk_hold_auto_refund_hours` with
#: nobody releasing or refunding it. `auto_refund_expired_holds` refunded it
#: automatically instead of leaving the customer's money in limbo forever.
#: Written on both the `refund_admin` call (as its `reason`) and the
#: `order_events` audit row this module adds alongside it.
REASON_AUTO_REFUND_HOLD_EXPIRED = "auto_refund_hold_expired"

#: Providers whose gateway `refund()` actually moves money, checked BEFORE
#: `_auto_refund_one` calls `payments.service.refund_admin` rather than
#: discovered by a raised `PaymentGatewayError` on every 15-minute tick.
#: Payme, Click (both `click` and `click_miniapp`), and Uzum — the three UZ
#: acquirers — are cabinet-refund-only: their `refund()` unconditionally
#: raises (see `gateways/{payme,click,uzum}.py` and
#: `docs/architecture/module-map.md`), so sending one of them through
#: `refund_admin` is not a retryable failure, it is a standing error forever
#: with no operator ever told. `mock` is the dev/test gateway, whose
#: `refund()` genuinely succeeds (`gateways/mock.py`) — real orders never
#: carry it in production.
_AUTO_REFUNDABLE_PROVIDERS = frozenset({"octo", "wallet", "mock"})


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
    REASON_LIQUID_AMOUNT: (
        "🔍 Крупная покупка ликвидного товара — на проверке",
        "Stars/Roblox/Steam выше порога для обналичиваемых товаров. Выдача НЕ "
        "запущена: проверь плательщика и серию, затем выдай или верни.",
    ),
    REASON_NEW_BUYER: (
        "🔍 Новый покупатель превысил стартовые лимиты",
        "Личность впервые видим на этой неделе, а покупок уже больше лимита. "
        "Выдача НЕ запущена — проверь и реши по всей серии.",
    ),
}


_TASHKENT_UTC_OFFSET = 5  # fixed, no DST


def _night_multiplier(at: datetime | None, cfg: Settings) -> Decimal:
    """Rule 4's factor: <1 between the configured Tashkent hours, 1 otherwise.

    The fraud waves this ruleset answers ran between one and five in the
    morning; the same amount that passes at noon deserves a human at 01:00.
    Pure — the caller passes the order's own paid-at, never the wall clock.
    """
    mult = cfg.risk_night_threshold_multiplier
    if at is None or mult >= 1:
        return Decimal("1")
    hour = (at.astimezone(UTC).hour + _TASHKENT_UTC_OFFSET) % 24
    start, end = cfg.risk_night_start_hour, cfg.risk_night_end_hour
    in_night = (start <= hour or hour < end) if start > end else (start <= hour < end)
    return mult if in_night else Decimal("1")


def _effective_threshold(order_id: str, cfg: Settings, *, base: Decimal | None = None) -> Decimal:
    """Rule 1's threshold for this order — jittered so probing finds a band,
    not an edge. Deterministic per order id: retries and tests are stable."""
    base = cfg.manual_review_threshold_usd if base is None else base
    if not cfg.risk_jitter or base <= 0:
        return base
    u = int.from_bytes(hashlib.sha256(order_id.encode()).digest()[:8], "big") / 2**64
    return base * (Decimal("0.6") + Decimal("0.4") * Decimal(str(u)))


def _amount_reason(order: Order, cfg: Settings, *, at: datetime | None = None) -> str | None:
    """Rule 1: is this single order, on its own, big enough to hold?"""
    threshold = _effective_threshold(order.id, cfg) * _night_multiplier(at, cfg)
    if cfg.manual_review_threshold_usd > 0 and order.total_usd >= threshold:
        return REASON_LARGE_AMOUNT
    return None


def _liquid_amount_reason(
    order: Order,
    brand_slugs: frozenset[str],
    cfg: Settings,
    *,
    at: datetime | None = None,
) -> str | None:
    """Rule 1b (Click rule 2): a tighter bar for cash-equivalent brands."""
    if cfg.risk_liquid_review_threshold_usd <= 0:
        return None
    liquid = _csv(cfg.risk_liquid_brands)
    if not liquid or not (brand_slugs & liquid):
        return None
    threshold = _effective_threshold(
        order.id, cfg, base=cfg.risk_liquid_review_threshold_usd
    ) * _night_multiplier(at, cfg)
    if order.total_usd >= threshold:
        return REASON_LIQUID_AMOUNT
    return None


def _new_buyer_reason(current: WindowOrder, recent: list[WindowOrder], cfg: Settings) -> str | None:
    """Click rule 3: fresh identities get three small purchases, then a human.

    "Fresh" means every linked order is younger than
    ``risk_new_buyer_age_days`` — one delivered order from last month is what
    separates a regular from a drop account, and regulars stay automatic.
    """
    if cfg.risk_new_buyer_velocity_24h <= 0 and cfg.risk_new_buyer_sum_24h_usd <= 0:
        return None
    linked = [r for r in recent if _shares_key(current, r)]
    age_limit = timedelta(days=cfg.risk_new_buyer_age_days)
    if any(current.paid_at - r.paid_at >= age_limit for r in linked):
        return None  # seasoned identity
    linked24 = [r for r in linked if r.paid_at >= current.paid_at - timedelta(hours=24)]
    if cfg.risk_new_buyer_velocity_24h > 0 and len(linked24) + 1 > cfg.risk_new_buyer_velocity_24h:
        return REASON_NEW_BUYER
    if (
        cfg.risk_new_buyer_sum_24h_usd > 0
        and current.total_usd + sum((r.total_usd for r in linked24), Decimal("0"))
        >= cfg.risk_new_buyer_sum_24h_usd
    ):
        return REASON_NEW_BUYER
    return None


@dataclass(frozen=True)
class WindowOrder:
    """One paid order's identity fingerprint, for the window rules (rules 2-4).

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
    db: AsyncSession, order: Order, cfg: Settings
) -> tuple[WindowOrder, list[WindowOrder], GeoContext]:
    """Assemble the current order's identity fingerprint, its recent paid
    siblings, and the geo context for rule 5.

    The current order's own evidence row (ip, device_hash, timezone) and its
    own items (delivery targets, brand slugs) are fetched first — everything
    below bounds itself against those, rather than pulling the whole trailing
    window and filtering in Python. At target scale (35k+ catalog orders paid
    in a rolling 7 days) an unfiltered fetch reads every one of them on every
    webhook; an identity-bound one reads only the orders that could possibly
    link to this one.

    Query A fetches other paid catalog orders in the trailing 7 days whose
    identity matches the current order's: same signed-in ``user_id``, same
    ``guest_email`` (``CITEXT``, already case-insensitive at the SQL layer —
    see also the defensive ``.lower()`` below, which is about a Python-side
    comparison, not this one), same evidence ``ip``, or — only when
    ``risk_device_identity`` is on, see ADR-0062 — same ``device_hash``. The
    ``OR`` list is built from whichever of those the current order actually
    has.

    The target path is separate because a delivery-target match lives inside
    ``order_items.fulfillment_data``, not on ``orders``/``order_evidence``:
    the current order's own targets are computed in Python first
    (``_targets_from``, reused so the normalisation can't drift), and only if
    that set is non-empty does an id query run, matching via
    ``jsonb_each_text`` with the same normalisation applied in SQL — strip
    whitespace, drop a leading ``@``, lowercase, same three steps as
    ``_targets_from`` in a different order that doesn't change the result
    (see the inline comment on the query). Skipped for voucher orders (empty
    ``fulfillment_data``), which is most orders.

    If the current order has no identity at all (no user, no guest email, no
    evidence row) and no delivery targets, nothing could possibly link to it,
    so no bounding query runs and ``recent`` is ``[]`` with no extra round
    trip.

    Otherwise the ids matched by identity and by target are unioned into one
    predicate, Query A fetches the full ``WindowOrder`` columns for that
    bounded id set, and Query B fetches ``fulfillment_data`` for the same
    bounded set (rather than every order in the window) to resolve their
    delivery targets.

    Runs inside ``db.begin_nested()`` (a SAVEPOINT) — the same pattern as
    ``evidence.service.capture_for_order``. Without it, a DB-level failure
    here (a statement/lock timeout, a dropped connection) poisons the
    request's transaction; the ``try/except`` below still swallows the
    exception, but the *next* statement — ``hold_for_review``'s own insert,
    or the commit at the end of the payment webhook — raises
    ``PendingRollbackError`` and takes the whole payment-success write down
    with it. The savepoint is what makes "a broken gather never blocks a
    sale" true for a DB-level abort, not only for a Python exception raised
    by one of these queries.

    Never raises: a broken risk query must degrade to the amount rule alone,
    not block a sale. On any failure this returns the current order with no
    identity, an empty recent list, and a ``GeoContext`` that cannot fire rule
    5 — ``is_guest=False`` alone is enough for that, but every field is left
    neutral so a partial read of this function's changes can't accidentally
    make it claim something it doesn't know.
    """
    try:
        async with db.begin_nested():
            window_start = now() - timedelta(days=7)
            base_frame = (
                Order.paid_at.is_not(None),
                Order.paid_at >= window_start,
                Order.id != order.id,
                Order.purpose == "catalog",
            )

            current_evidence_row = (
                await db.execute(
                    select(
                        OrderEvidence.ip, OrderEvidence.device_hash, OrderEvidence.client_hints
                    ).where(OrderEvidence.order_id == order.id)
                )
            ).first()
            raw_tz = current_evidence_row[2].get("timezone") if current_evidence_row else None
            timezone = raw_tz if isinstance(raw_tz, str) else None
            current_ip = current_evidence_row[0] if current_evidence_row else None
            # Choke point for finding 4: when device identity is off, the
            # current order's device is None from here on, which means
            # nothing below — the SQL predicate, the current WindowOrder, the
            # matched rows' WindowOrders — can ever link on it.
            current_device = (
                current_evidence_row[1]
                if current_evidence_row and cfg.risk_device_identity
                else None
            )
            current_user_id = order.user_id
            # Defensive: CITEXT makes the SQL predicate below case-insensitive
            # already, but `_window_reason`/`_shares_key` compare `WindowOrder`
            # values with plain Python `==`, which is not. Lowering here is
            # what makes "same email in different case" actually link.
            current_guest_email = order.guest_email.lower() if order.guest_email else None

            current_item_rows = (
                await db.execute(
                    select(OrderItem.fulfillment_data, Brand.slug)
                    .select_from(OrderItem)
                    .join(Sku, Sku.id == OrderItem.sku_id)
                    .join(Product, Product.id == Sku.product_id)
                    .join(Brand, Brand.id == Product.brand_id)
                    .where(OrderItem.order_id == order.id)
                )
            ).all()
            current_targets: set[str] = set()
            brand_slugs: set[str] = set()
            for fulfillment_data, brand_slug in current_item_rows:
                current_targets.update(_targets_from(fulfillment_data))
                brand_slugs.add(brand_slug)

            identity_predicates = []
            if current_user_id is not None:
                identity_predicates.append(Order.user_id == current_user_id)
            if current_guest_email is not None:
                identity_predicates.append(Order.guest_email == current_guest_email)
            if current_ip is not None:
                identity_predicates.append(OrderEvidence.ip == current_ip)
            if current_device is not None:
                identity_predicates.append(OrderEvidence.device_hash == current_device)

            target_ids: set[str] = set()
            if current_targets:
                # Same normalisation as `_targets_from`, reordered to match
                # Postgres's function set (strip -> drop leading '@' -> lower
                # instead of strip -> lower -> drop leading '@'); `@` has no
                # case and stripped whitespace can't reintroduce one, so the
                # two orders agree on every input. See the 0059 backfill for
                # the same "SQL must byte-match the Python helper" pairing.
                target_id_rows = (
                    (
                        await db.execute(
                            select(OrderItem.order_id)
                            .distinct()
                            .select_from(OrderItem)
                            .join(Order, Order.id == OrderItem.order_id)
                            .where(
                                *base_frame,
                                text(
                                    "EXISTS (SELECT 1 FROM jsonb_each_text("
                                    "order_items.fulfillment_data) kv WHERE "
                                    "lower(ltrim(btrim(kv.value), '@')) = ANY(:targets))"
                                ).bindparams(
                                    bindparam(
                                        "targets",
                                        value=sorted(current_targets),
                                        type_=ARRAY(Text),
                                    )
                                ),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                target_ids.update(target_id_rows)

            matched_predicates = list(identity_predicates)
            if target_ids:
                matched_predicates.append(Order.id.in_(target_ids))

            recent: list[WindowOrder] = []
            if matched_predicates:
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
                        .where(*base_frame, or_(*matched_predicates))
                    )
                ).all()
                matched_ids = [row[0] for row in rows]
                item_rows = (
                    await db.execute(
                        select(OrderItem.order_id, OrderItem.fulfillment_data).where(
                            OrderItem.order_id.in_(matched_ids)
                        )
                    )
                ).all()
                targets_by_order: dict[str, set[str]] = {}
                for order_id, fulfillment_data in item_rows:
                    targets_by_order.setdefault(order_id, set()).update(
                        _targets_from(fulfillment_data)
                    )
                recent = [
                    WindowOrder(
                        id=row[0],
                        paid_at=row[1],
                        total_usd=row[2],
                        buyer=row[3] or (row[4].lower() if row[4] else None),
                        ip=row[5],
                        device=row[6] if cfg.risk_device_identity else None,
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
                buyer=current_user_id or current_guest_email,
                ip=current_ip,
                device=current_device,
                targets=frozenset(current_targets),
            )
            geo = GeoContext(
                is_guest=order.user_id is None,
                brand_slugs=frozenset(brand_slugs),
                timezone=timezone,
            )
    except Exception:
        log.exception("orders.risk.gather_failed", order_id=order.id)
        return (
            WindowOrder(
                id=order.id,
                paid_at=order.paid_at or now(),
                total_usd=order.total_usd,
                buyer=order.user_id or (order.guest_email.lower() if order.guest_email else None),
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
    never raise on their own — a failed ``_gather`` is logged and this
    continues into them with a neutral context (an empty recent list, a
    ``GeoContext`` that cannot fire rule 5) rather than skipping them. That is
    not the same as "rule 1 alone": the rolling-sum rule counts the order
    under review against itself (ADR-0062), so a single order at or above
    `risk_sum_24h_usd`/`risk_sum_7d_usd` still holds even with zero siblings
    read.
    """
    cfg = settings or get_settings()
    paid_at = getattr(order, "paid_at", None)
    amount = _amount_reason(order, cfg, at=paid_at)
    if amount is not None:
        return amount
    current, recent, geo = await _gather(db, order, cfg)
    liquid = _liquid_amount_reason(order, geo.brand_slugs, cfg, at=paid_at)
    if liquid is not None:
        return liquid
    window = _window_reason(current, recent, cfg)
    if window is not None:
        return window
    fresh = _new_buyer_reason(current, recent, cfg)
    if fresh is not None:
        return fresh
    return _geo_reason(geo.is_guest, geo.brand_slugs, geo.timezone, cfg)


def _veto_decision(
    is_trusted: bool,
    country: str | None,
    timezone: str | None,
    cfg: Settings,
) -> str | None:
    """Pure decision core for the pre-charge veto. See ADR-0063.

    Both enforcement points call this with their own inputs (the acquirer
    stage from the stored evidence row, order creation from the live
    request) so they can never drift from each other.

    Country beats timezone when both are present: the country is
    Cloudflare's own read of the request's network path
    (``order_evidence.ip_country``); the timezone is whatever the browser
    self-reports. A VPN into a home country with a foreign clock is real,
    but it is the post-payment hold's (ADR-0062) job to notice, not a
    pre-charge refusal on a guess.

    Args:
        is_trusted: Whether the order's buyer already has a delivered order
            — see ``_is_trusted_buyer``. Exempt from every check below: a
            fresh account earns nothing (registration costs a carder thirty
            seconds), but a proven customer travelling abroad is not treated
            as one.
        country: ``order_evidence.ip_country`` (or the live ``cf-ipcountry``
            header at the creation enforcement point). ``None`` when the
            header was absent or no evidence row exists.
        timezone: The evidence/client-hint timezone. Consulted only when
            ``country`` is absent — the fallback, not a second opinion once
            the network has already spoken.
        cfg: Settings, so callers can pin a config without mutating the
            process-wide singleton.

    Returns:
        ``VETO_FOREIGN_COUNTRY``, ``VETO_FOREIGN_TIMEZONE``, or ``None``.
    """
    if not cfg.risk_precharge_veto:
        return None
    if is_trusted:
        return None
    if country is not None:
        home_countries = _csv(cfg.risk_home_countries)
        if home_countries and country.strip().lower() not in home_countries:
            return VETO_FOREIGN_COUNTRY
        return None
    if timezone is not None:
        home_timezones = _csv(cfg.risk_home_timezones)
        if home_timezones and timezone.strip().lower() not in home_timezones:
            return VETO_FOREIGN_TIMEZONE
    return None


async def _is_trusted_buyer(db: AsyncSession, user_id: str | None) -> bool:
    """Whether ``user_id`` has ever had an order actually delivered.

    A guest (``user_id is None``) is never trusted — there is no history to
    check. A signed-in user with zero delivered orders is treated the same
    as a guest: registration costs a carder nothing, so the exemption is
    earned by something real having shipped, not merely by having an
    account.

    Args:
        db: Session.
        user_id: The order's ``user_id``, or ``None`` for a guest checkout.

    Returns:
        ``True`` when at least one of this user's orders has
        ``status="delivered"``.
    """
    if user_id is None:
        return False
    count = (
        await db.execute(
            select(func.count())
            .select_from(Order)
            .where(Order.user_id == user_id, Order.status == "delivered")
        )
    ).scalar_one()
    return count >= 1


class PrechargeVetoResult(NamedTuple):
    """``precharge_veto_full``'s answer: the decision plus what drove it.

    ``reason`` is exactly what ``precharge_veto`` returns. ``country`` /
    ``timezone`` are the same ``order_evidence`` values the decision was made
    from, handed back so a caller that needs them (``record_precharge_veto``)
    doesn't re-read the row a second time — that second read used to be
    ``evidence_geo``, now gone.
    """

    reason: str | None
    country: str | None
    timezone: str | None


async def precharge_veto_full(
    db: AsyncSession,
    order: Order,
    *,
    settings: Settings | None = None,
) -> PrechargeVetoResult:
    """Whether this order's charge must be refused before it happens, plus why.

    ADR-0063. Fed from the order's stored ``order_evidence`` row — the
    acquirer pre-charge stages (Payme ``CheckPerformTransaction``, Click
    ``Prepare``, Uzum ``Check``) call this directly, then hand
    ``result.country``/``result.timezone`` straight to
    ``record_precharge_veto`` without a second SELECT of the same row. Order
    creation instead calls ``_veto_decision`` straight, fed from the live
    request, since refusing creation rolls the transaction back and leaves no
    evidence row to read.

    Never raises: a broken veto must fail open to "charge allowed", the same
    way ``_gather`` fails open to "no window claim" — the post-payment hold
    (ADR-0062) is the net beneath both. Runs inside ``db.begin_nested()`` for
    the same reason ``_gather`` does: a DB-level abort here must not poison
    the caller's transaction.

    Args:
        db: Session. The caller owns the transaction.
        order: The order under evaluation. Only ``.id``, ``.purpose`` and
            ``.user_id`` are read.
        settings: Override for tests; defaults to the process settings.

    Returns:
        A ``PrechargeVetoResult``. ``country``/``timezone`` are ``None``
        whenever the evidence row is missing the value or missing entirely,
        or the checks were skipped/failed (non-catalog order, disabled veto,
        broken query) — a caller must key off ``reason``, not assume
        ``country``/``timezone`` are populated just because they're present.
    """
    if order.purpose != "catalog":
        return PrechargeVetoResult(None, None, None)
    cfg = settings or get_settings()
    try:
        async with db.begin_nested():
            row = (
                await db.execute(
                    select(OrderEvidence.ip_country, OrderEvidence.client_hints).where(
                        OrderEvidence.order_id == order.id
                    )
                )
            ).first()
            country = row[0] if row else None
            raw_tz = row[1].get("timezone") if row else None
            timezone = raw_tz if isinstance(raw_tz, str) else None
            trusted = await _is_trusted_buyer(db, order.user_id)
    except Exception:
        log.exception("orders.risk.veto_failed", order_id=order.id)
        return PrechargeVetoResult(None, None, None)
    reason = _veto_decision(trusted, country, timezone, cfg)
    return PrechargeVetoResult(reason, country, timezone)


async def precharge_veto(
    db: AsyncSession,
    order: Order,
    *,
    settings: Settings | None = None,
) -> str | None:
    """Whether this order's charge must be refused before it happens. ADR-0063.

    Thin wrapper over ``precharge_veto_full`` for callers that only need the
    reason (tests, and anywhere ``country``/``timezone`` don't matter) — see
    that function's docstring for the full contract.

    Returns:
        ``VETO_FOREIGN_COUNTRY``, ``VETO_FOREIGN_TIMEZONE``, or ``None``.
    """
    return (await precharge_veto_full(db, order, settings=settings)).reason


async def record_precharge_veto(
    db: AsyncSession,
    order: Order,
    reason: str,
    *,
    country: str | None,
    timezone: str | None,
) -> None:
    """Record a pre-charge refusal. ADR-0063, enforcement point A.

    Idempotent per order: an acquirer retries a refused CheckPerform/
    Prepare/Check verbatim, so without the guard below a single veto would
    write one event per retry. The caller raises the acquirer's own
    "not payable" error immediately after this returns — that raise rolls
    the request's transaction back, which would silently erase the row this
    function just added, so this commits it NOW rather than leaving it for
    the caller (mirrors ``payments.service``'s "Commit NOW" webhook-rejection
    and refund-rejection paths).

    ``country``/``timezone`` are codes, not addresses — the IP they were
    derived from never leaves ``order_evidence``.

    Args:
        db: Active session.
        order: The vetoed order.
        reason: ``VETO_FOREIGN_COUNTRY`` or ``VETO_FOREIGN_TIMEZONE`` (from
            ``precharge_veto``).
        country: The evidence value that drove the decision, or ``None``.
        timezone: The evidence value that drove the decision, or ``None``.
    """
    # The existence-check-then-insert below is only idempotent under
    # serialization on this order. Two of the four call sites already lock
    # the order upstream (Click ``prepare``, Payme ``create_transaction``,
    # both via ``_resolve_order(..., for_update=True)``); the other two
    # (Payme ``check_perform_transaction``, Uzum ``check``) do not — so two
    # truly concurrent retries could both pass the SELECT and each insert
    # their own event. Locking here makes the guarantee this function's own
    # rather than an accident of which callers happen to lock upstream. A
    # caller that already holds this row's lock (same transaction) just
    # re-acquires it — a no-op, not a deadlock.
    await db.execute(select(Order.id).where(Order.id == order.id).with_for_update())
    existing = (
        await db.execute(
            select(OrderEvent.id).where(
                OrderEvent.order_id == order.id,
                OrderEvent.kind == "order.precharge_vetoed",
            )
        )
    ).first()
    if existing is not None:
        return
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind="order.precharge_vetoed",
            payload={"reason": reason, "country": country, "timezone": timezone},
            actor="risk",
        )
    )
    log.warning("orders.precharge_vetoed", order_id=order.id, reason=reason)
    # Commit NOW: the raise right after this call makes the request
    # transaction roll back, which would silently erase this audit row
    # otherwise.
    await db.commit()


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

    # Click rule 5 (2026-09-02): the hold alert carries what the provider's
    # fraud team needs to say «пропускать/блокировать» — product, provider,
    # payment time and the delivery target MASKED (first three characters) —
    # so the operator can forward the message to them as-is. Identities never
    # ride along: a group chat is not a place for another buyer's email.
    facts: dict[str, str] = {}
    with contextlib.suppress(Exception):
        facts = await _fraud_group_facts(db, order)

    charged = format_amount(order.total_charged, order.currency)
    title, what_to_do = HOLD_ALERT_TEXT.get(reason, HOLD_ALERT_TEXT[REASON_LARGE_AMOUNT])
    fact_lines = "".join(f"{k.capitalize()}: {v}\n" for k, v in facts.items())
    paid_line = f"Оплачен: {order.paid_at:%d.%m %H:%M} UTC\n" if order.paid_at else ""
    with contextlib.suppress(Exception):
        await send_admin_alert(
            f"<b>{title}</b>\n"
            f"Заказ: <code>{order.id[:8]}…</code>\n"
            f"Сумма: <b>{charged} {order.currency}</b> (${order.total_usd})\n"
            f"{fact_lines}"
            f"{paid_line}"
            f"<i>{what_to_do}</i>",
            kind="order_held_for_review",
        )

    # Optional second copy into a dedicated shared fraud group, for the day
    # a provider wants to sit in one — off while TG_FRAUD_CHAT_ID is unset;
    # today the operator forwards from the main alert group by hand.
    fraud_chat = get_settings().tg_fraud_chat_id
    if fraud_chat:
        with contextlib.suppress(Exception):
            await send_admin_alert(
                _fraud_group_text(facts, order, reason),
                kind="fraud_review",
                chat_id=fraud_chat,
            )


async def _fraud_group_facts(db: AsyncSession, order: Order) -> dict[str, str]:
    """Product, provider and masked recipient for the shared-group alert."""
    from yupay.modules.catalog.models import Sku
    from yupay.modules.orders.models import OrderItem
    from yupay.modules.payments.models import Payment

    facts: dict[str, str] = {}
    row = (
        await db.execute(
            select(Sku.sku_code, OrderItem.qty, OrderItem.fulfillment_data)
            .join(Sku, Sku.id == OrderItem.sku_id)
            .where(OrderItem.order_id == order.id)
            .limit(1)
        )
    ).first()
    if row is not None:
        sku_code, qty, data = row
        facts["товар"] = f"{sku_code} × {qty}"
        target = ""
        if isinstance(data, dict):
            target = str(
                data.get("username") or data.get("player_id") or data.get("steam_login") or ""
            )
        if target:
            facts["получатель"] = f"{target[:3]}***"
    provider = (
        await db.execute(select(Payment.provider).where(Payment.order_id == order.id).limit(1))
    ).scalar_one_or_none()
    if provider:
        facts["провайдер"] = provider
    return facts


def _fraud_group_text(facts: dict[str, str], order: Order, reason: str) -> str:
    charged = format_amount(order.total_charged, order.currency)
    lines = [
        "⚠️ <b>Заказ задержан антифродом — нужна проверка</b>",
        f"Сумма: <b>{charged} {order.currency}</b>",
        *(f"{k.capitalize()}: {v}" for k, v in facts.items()),
        f"Время оплаты: {order.paid_at:%d.%m %H:%M} UTC" if order.paid_at else "",
        f"Правило: <code>{reason}</code>",
        "Ответьте «пропустить» или «блокировать» — выдача остановлена до решения.",
    ]
    return "\n".join(line for line in lines if line)


async def _escalate_auto_refund(
    db: AsyncSession, order: Order, *, provider: str, hours: int
) -> None:
    """Hand a held order's refund to a human instead of retrying it forever.

    ``provider`` is not in ``_AUTO_REFUNDABLE_PROVIDERS`` — Payme, Click, or
    Uzum (or any other future cabinet-refund-only gateway) — so
    ``payments.service.refund_admin`` would call ``gw.refund()``, which
    unconditionally raises (see ``gateways/{payme,click,uzum}.py``). Without
    this branch, ``_auto_refund_one`` would commit a fresh error
    ``payment_attempts`` row on this order every 15 minutes, forever, with no
    operator ever told.

    Escalates exactly once per order: the caller's selection query
    (``auto_refund_expired_holds``) excludes any order that already has an
    ``order.auto_refund_escalated`` event, so this never runs twice for the
    same order.

    Args:
        db: Active session, holding the order's row lock (see
            ``_auto_refund_one``).
        order: The held order. Only ``.id``, ``.total_charged``,
            ``.currency`` are read.
        provider: The payment's provider slug, for the event payload and the
            alert — never PII, just an acquirer name.
        hours: The configured deadline, echoed in the event payload and alert
            text the same way ``_auto_refund_one`` does for an actual refund.
    """
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order.id,
            kind="order.auto_refund_escalated",
            payload={"provider": provider, "deadline_hours": hours},
            actor="risk",
        )
    )
    log.warning("orders.auto_refund_escalated", order_id=order.id, provider=provider)
    # Commit NOW, same reasoning as the refund path below: this event is the
    # one durable signal that keeps the next tick from re-escalating.
    await db.commit()

    from yupay.modules.notifications.alerts import send_admin_alert

    charged = format_amount(order.total_charged, order.currency)
    with contextlib.suppress(Exception):
        await send_admin_alert(
            "<b>⚠️ Автовозврат недоступен — деньги надо вернуть из кабинета эквайера</b>\n"
            f"Заказ: <code>{order.id[:8]}…</code>\n"
            f"Сумма: <b>{charged} {order.currency}</b>\n"
            f"Провайдер: <b>{provider}</b>\n"
            f"<i>{provider} не поддерживает возврат через API. Зайди в кабинет "
            f"{provider}, найди платёж по заказу и оформи возврат там — "
            "коллбэк от эквайера сам переведёт заказ в refunded. Подробности: "
            "runbook order-held-for-review.md.</i>",
            kind="order_auto_refund_escalated",
        )


async def _auto_refund_one(db: AsyncSession, order_id: str, *, hours: int) -> bool:
    """Refund one order held past its deadline. Returns whether it refunded.

    Re-verifies eligibility under a row lock immediately before refunding.
    The batch this is called from snapshots up to ``limit`` order ids and
    then processes them one at a time with real gateway calls in between —
    long enough for an operator to release the order
    (``fulfillment.start_for_order``) or mark it failed
    (``orders.service.mark_order_failed_admin``) in the gap between the
    snapshot and this order's turn. ``SELECT ... FOR UPDATE`` serializes this
    check against any concurrent writer of the same row; a status that has
    already left ``paid`` by the time this runs is not a failure, just a sign
    this order is no longer this function's to touch — logged and skipped,
    the same as "no payment found" below, never treated as an error. Both
    skip paths roll the transaction back before returning: the ``FOR UPDATE``
    lock taken above otherwise survives, unreleased, all the way to the
    tick's session close.

    Looks up the order's succeeded payment itself (the sweep has no route
    handler to hand it one). When that payment's provider actually supports a
    merchant-initiated refund (``_AUTO_REFUNDABLE_PROVIDERS``), refunds it in
    full through :func:`payments.service.refund_admin` — the same admin
    refund chokepoint, keyed by a deterministic ``auto-refund:<order_id>``
    idempotency key rather than a fresh one per tick, which is what makes a
    crashed-and-rerun tick safe: a retried call with the same key replays
    ``refund_admin``'s own result instead of hitting the gateway twice.
    Otherwise (Payme, Click, Uzum — cabinet-refund-only) hands the order to
    :func:`_escalate_auto_refund` instead of ever calling ``refund_admin``,
    which would just fail.

    Commits immediately on success — this order's refund, ledger posting, and
    audit event land as one durable unit before the caller moves on to the
    next order, so a crash mid-sweep can only ever lose *unstarted* work, not
    roll back an order this function already told an operator was refunded.

    Never raises to the caller in the way that matters for the sweep: an
    exception from ``refund_admin`` (a down acquirer, a stale payment state)
    propagates so :func:`auto_refund_expired_holds` can log it and move on to
    the next order — this function's job is only to keep its own commit
    boundary tight, not to swallow the error.
    """
    # Locked here, and never re-locked before `refund_admin` reads the same
    # row again inside `_apply_refund_reversal` — same transaction, same
    # identity map, so that later read is a cheap re-fetch of an already-held
    # lock, not a second lock acquisition to deadlock against.
    order = (
        await db.execute(select(Order).where(Order.id == order_id).with_for_update())
    ).scalar_one_or_none()
    if order is None or order.status != "paid":
        log.info(
            "orders.risk.auto_refund_no_longer_eligible",
            order_id=order_id,
            status=order.status if order is not None else None,
        )
        await db.rollback()
        return False

    payment_row = (
        await db.execute(
            select(Payment.id, Payment.provider)
            .where(Payment.order_id == order_id, Payment.status == "succeeded")
            .order_by(Payment.succeeded_at.desc())
            .limit(1)
        )
    ).first()
    if payment_row is None:
        # Shouldn't happen — a `paid` order has a succeeded payment by
        # definition — but a broken invariant here must be loud, not a crash
        # that takes the rest of the batch down with it.
        log.error("orders.risk.auto_refund_no_payment", order_id=order_id)
        await db.rollback()
        return False
    payment_id, provider = payment_row

    if provider not in _AUTO_REFUNDABLE_PROVIDERS:
        await _escalate_auto_refund(db, order, provider=provider, hours=hours)
        return False

    total_charged, currency = order.total_charged, order.currency

    from yupay.modules.payments import service as payments_svc

    await payments_svc.refund_admin(
        db,
        payment_id=payment_id,
        admin_id="auto-refund-sweep",
        reason=REASON_AUTO_REFUND_HOLD_EXPIRED,
        idempotency_key=f"auto-refund:{order_id}",
    )
    db.add(
        OrderEvent(
            id=new_id(),
            order_id=order_id,
            kind="order.auto_refund_hold_expired",
            payload={"payment_id": payment_id, "hours": hours},
            actor="risk",
        )
    )
    log.warning("orders.auto_refund_hold_expired", order_id=order_id, hours=hours)
    # Commit NOW: this is the one durable unit — payment/order/ledger (already
    # flushed by `refund_admin`) plus the audit event above — that a
    # crashed-and-rerun tick must be able to trust already happened.
    await db.commit()

    from yupay.modules.notifications.alerts import send_admin_alert

    charged = format_amount(total_charged, currency)
    with contextlib.suppress(Exception):
        await send_admin_alert(
            "<b>💸 Автовозврат: срок проверки истёк</b>\n"
            f"Заказ: <code>{order_id[:8]}…</code>\n"
            f"Сумма: <b>{charged} {currency}</b> возвращена покупателю\n"
            f"<i>Заказ был на проверке дольше {hours} ч, никто не выпустил и не "
            "вернул его вручную — это текущая политика "
            "(RISK_HOLD_AUTO_REFUND_HOURS), не сбой.</i>",
            kind="order_auto_refund_hold_expired",
        )
    return True


async def auto_refund_expired_holds(
    db: AsyncSession,
    *,
    settings: Settings | None = None,
    limit: int = 50,
) -> int:
    """Refund or escalate every held order whose deadline has passed. ADR-0063.

    ``hold_for_review`` (rules 1-5, ADR-0047/0062) leaves a paid catalog
    order on hold indefinitely until an operator releases it (starts
    fulfilment — the FSM's own ``paid`` -> ``fulfilling`` transition, see
    ``fulfillment.start_for_order``) or refunds it by hand. Nothing enforced
    a deadline on that decision before this function: an alert that is
    missed is a hold that sits forever. ``risk_hold_auto_refund_hours`` is
    that deadline. "Refund" is only literal for a provider in
    ``_AUTO_REFUNDABLE_PROVIDERS``; a held order paid through Payme, Click, or
    Uzum is escalated to a human instead (``_escalate_auto_refund``) — see
    that function and ``_auto_refund_one``.

    Selection is ``status="paid"`` + ``purpose="catalog"`` + a succeeded
    payment + an ``order.held_for_review`` event older than the deadline +
    no ``order.auto_refund_escalated`` event yet. ``status="paid"`` rules out
    a *released* order (``start_for_order`` moves it to ``fulfilling``) and a
    wallet top-up (``purpose != "catalog"``, nothing to release in the first
    place), but it does **not** by itself mean "nobody has acted on this
    hold": ``orders.service.mark_order_failed_admin`` can also move a held
    order off ``paid`` (to ``failed``) without moving any money. An order
    closed that way drops out of this sweep's selection with its payment
    still ``succeeded`` — a known gap, documented (not closed) in ADR-0063
    and the runbook, because closing it here would mean the sweep guessing at
    money an operator explicitly chose not to move yet. The succeeded-payment
    filter exists for a narrower reason: a *partially* refunded hold leaves
    its payment ``partially_refunded``, not ``succeeded``, so without this
    filter the same order would be re-selected and fail every 15 minutes
    forever (``refund_admin`` rejects a second refund of a non-``succeeded``
    payment) — filtering it out here is what keeps that a clean no-op instead
    of a standing error. The escalated-event exclusion exists for the same
    shape of reason on the cabinet-only path: without it, an already-
    escalated order would be re-selected, re-alerted, and get a second
    ``order.auto_refund_escalated`` row every 15 minutes forever, even though
    ``refund_admin`` is never actually called for it. Every hold reason
    otherwise stays in scope, including ``REASON_PAID_AFTER_EXPIRY`` — the
    spec calls for the same safe default regardless of which rule put the
    order on hold.

    Runs in ``limit``-sized batches so one call bounds its own work; the
    scheduler wrapper (``yupay_scheduler.jobs.held_order_refund``) loops this
    across batches so a backlog bigger than one batch still drains in a
    single tick.

    Per-order try/except: one acquirer's refund API being down (or any other
    single-order failure) is logged and the sweep moves on to the next order
    rather than losing the whole batch — ``db.rollback()`` on failure clears
    whatever the failed attempt left half-written so the next order's queries
    aren't run against an aborted transaction.

    Args:
        db: Active session. Each successfully refunded or escalated order
            commits its own work (see ``_auto_refund_one``,
            ``_escalate_auto_refund``); the caller does not need to commit
            around this call.
        settings: Override for tests; defaults to the process settings.
        limit: Maximum orders processed in this call.

    Returns:
        How many orders were actually refunded — escalated orders don't
        count, since no money moved for them.
    """
    cfg = settings or get_settings()
    hours = cfg.risk_hold_auto_refund_hours
    if hours <= 0:
        return 0
    cutoff = now() - timedelta(hours=hours)

    held_order_ids = (
        select(OrderEvent.order_id)
        .where(OrderEvent.kind == "order.held_for_review", OrderEvent.created_at <= cutoff)
        .distinct()
    )
    # A partially refunded hold's payment is `partially_refunded`, not
    # `succeeded` — excluded here so it never re-enters the batch and fails
    # `refund_admin`'s "already refunded" guard on every tick forever.
    succeeded_payment_order_ids = select(Payment.order_id).where(Payment.status == "succeeded")
    # Already escalated once (a cabinet-only provider, see
    # `_escalate_auto_refund`) — excluded so a later tick neither re-alerts
    # nor re-attempts it.
    escalated_order_ids = select(OrderEvent.order_id).where(
        OrderEvent.kind == "order.auto_refund_escalated"
    )
    order_ids = (
        (
            await db.execute(
                select(Order.id)
                .where(
                    Order.status == "paid",
                    Order.purpose == "catalog",
                    Order.id.in_(held_order_ids),
                    Order.id.in_(succeeded_payment_order_ids),
                    Order.id.not_in(escalated_order_ids),
                )
                .order_by(Order.paid_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    refunded = 0
    for order_id in order_ids:
        try:
            if await _auto_refund_one(db, order_id, hours=hours):
                refunded += 1
        except Exception:
            log.exception("orders.risk.auto_refund_failed", order_id=order_id)
            with contextlib.suppress(Exception):
                await db.rollback()
    return refunded


__all__ = [
    "HOLD_ALERT_TEXT",
    "REASON_AUTO_REFUND_HOLD_EXPIRED",
    "REASON_GEO_MISMATCH",
    "REASON_LARGE_AMOUNT",
    "REASON_PAID_AFTER_EXPIRY",
    "REASON_ROLLING_SUM",
    "REASON_SHARED_IDENTITY",
    "REASON_VELOCITY",
    "VETO_FOREIGN_COUNTRY",
    "VETO_FOREIGN_TIMEZONE",
    "GeoContext",
    "PrechargeVetoResult",
    "WindowOrder",
    "auto_refund_expired_holds",
    "hold_for_review",
    "precharge_veto",
    "precharge_veto_full",
    "record_precharge_veto",
    "review_reason",
]
