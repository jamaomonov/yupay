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
behind it instead of trusting it to be seen.
"""

from __future__ import annotations

import contextlib
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Text, bindparam, func, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
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
    amount = _amount_reason(order, cfg)
    if amount is not None:
        return amount
    current, recent, geo = await _gather(db, order, cfg)
    window = _window_reason(current, recent, cfg)
    if window is not None:
        return window
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


async def precharge_veto(
    db: AsyncSession,
    order: Order,
    *,
    settings: Settings | None = None,
) -> str | None:
    """Whether this order's charge must be refused before it happens. ADR-0063.

    Fed from the order's stored ``order_evidence`` row — the acquirer
    pre-charge stages (Payme ``CheckPerformTransaction``, Click ``Prepare``,
    Uzum ``Check``) call this directly; order creation instead calls
    ``_veto_decision`` straight, fed from the live request, since refusing
    creation rolls the transaction back and leaves no evidence row to read.

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
        ``VETO_FOREIGN_COUNTRY``, ``VETO_FOREIGN_TIMEZONE``, or ``None``.
    """
    if order.purpose != "catalog":
        return None
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
        return None
    return _veto_decision(trusted, country, timezone, cfg)


async def evidence_geo(db: AsyncSession, order_id: str) -> tuple[str | None, str | None]:
    """Return the order's stored ``(ip_country, timezone)``, or ``(None, None)``.

    Reads the same ``order_evidence`` columns ``precharge_veto`` itself
    decided from. Enforcement point A (the acquirer pre-charge stages) calls
    this right after a veto fires, purely to log which values drove the
    refusal — it never repeats the decision, only echoes what already made
    it.

    Args:
        db: Active session.
        order_id: The vetoed order's id.

    Returns:
        ``(ip_country, timezone)``. Either element, or the whole pair, is
        ``None`` when the evidence row is missing the value or missing
        entirely.
    """
    row = (
        await db.execute(
            select(OrderEvidence.ip_country, OrderEvidence.client_hints).where(
                OrderEvidence.order_id == order_id
            )
        )
    ).first()
    if row is None:
        return None, None
    raw_tz = row[1].get("timezone") if row[1] else None
    return row[0], raw_tz if isinstance(raw_tz, str) else None


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


async def _auto_refund_one(db: AsyncSession, order_id: str, *, hours: int) -> bool:
    """Refund one order held past its deadline. Returns whether it refunded.

    Looks up the order's succeeded payment itself (the sweep has no route
    handler to hand it one) and refunds it in full through
    :func:`payments.service.refund_admin` — the same admin refund chokepoint,
    keyed by a deterministic ``auto-refund:<order_id>`` idempotency key rather
    than a fresh one per tick, which is what makes a crashed-and-rerun tick
    safe: a retried call with the same key replays ``refund_admin``'s own
    result instead of hitting the gateway twice.

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
    payment_row = (
        await db.execute(
            select(Payment.id, Order.total_charged, Order.currency)
            .select_from(Payment)
            .join(Order, Order.id == Payment.order_id)
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
        return False
    payment_id, total_charged, currency = payment_row

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

    charged = f"{total_charged:,.0f}".replace(",", " ")
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
    """Refund every held order whose deadline has passed. ADR-0063.

    ``hold_for_review`` (rules 1-5, ADR-0047/0062) leaves a paid catalog
    order on hold indefinitely until an operator releases it (starts
    fulfilment — the FSM's own ``paid`` -> ``fulfilling`` transition, see
    ``fulfillment.start_for_order``) or refunds it by hand. Nothing enforced
    a deadline on that decision before this function: an alert that is
    missed is a hold that sits forever. ``risk_hold_auto_refund_hours`` is
    that deadline.

    Selection is ``status="paid"`` + ``purpose="catalog"`` + an
    ``order.held_for_review`` event older than the deadline. ``status="paid"``
    alone is enough to mean "not yet released": ``start_for_order`` is the
    only thing that ever moves a paid order off ``paid`` for a reason other
    than a refund, and it always moves it to ``fulfilling`` — so a released
    order is never re-selected here, and neither is a wallet top-up
    (``purpose != "catalog"``, no fulfilment to release in the first place).
    Every hold reason is in scope, including
    ``REASON_PAID_AFTER_EXPIRY`` — the spec calls for the same safe default
    regardless of which rule put the order on hold.

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
        db: Active session. Each successfully refunded order commits its own
            work (see ``_auto_refund_one``); the caller does not need to
            commit around this call.
        settings: Override for tests; defaults to the process settings.
        limit: Maximum orders refunded in this call.

    Returns:
        How many orders were refunded.
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
    order_ids = (
        (
            await db.execute(
                select(Order.id)
                .where(
                    Order.status == "paid",
                    Order.purpose == "catalog",
                    Order.id.in_(held_order_ids),
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
    "WindowOrder",
    "auto_refund_expired_holds",
    "evidence_geo",
    "hold_for_review",
    "precharge_veto",
    "record_precharge_veto",
    "review_reason",
]
