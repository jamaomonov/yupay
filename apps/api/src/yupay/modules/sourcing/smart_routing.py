"""Smart routing: the hourly job that keeps managed SKUs on the right supplier (ADR-0108).

Thousands of SKUs have two or more suppliers; nobody can watch every route by
hand. For each rule marked ``managed`` this job moves ``supplier_slug`` to the
cheapest supplier that can sell right now — with brakes the prod data asked for
(2026-11-24): suppliers sit within 1 % of each other 85 % of the time, and with
no threshold the route would have flipped 27 346 times in 14 days.

- **Cheaper:** move only when at least ``smart_switch_pct`` (1 %) cheaper, and
  not within ``smart_dwell_hours`` (6 h) of the last move.
- **Cannot sell** (out of stock, delisted, no price, quarantined): move to the
  cheapest that can, if it is at most ``smart_stock_step_pct`` (6 %) dearer;
  otherwise stay and log ``blocked``. The dwell does not hold this one back.
- **Quarantine:** three failures of one supplier on one SKU in 24 h sit it out
  6 h; failing again on its first orders back doubles it (12 h, then 24 h). So
  a supplier that is cheapest but does not deliver is not moved straight back.
- **Never** a pinned rule (``managed`` false — every operator save), never the
  warehouse or the manual queue.

``smart_mode``: ``off`` does nothing, ``shadow`` only logs what it would do,
``on`` moves. A move re-prices the SKU as an operator's switch does
(``cost_refresh.refresh_routed_cost``, ADR-0091). Turning it off freezes every
route where it stands — the behaviour before this ADR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.db import get_session_factory
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.sourcing.models import SkuSourcingRule, SourcingQuarantine, SourcingSwitchLog

log = get_logger("yupay.sourcing.smart_routing")

ACTOR: Final = "system:smart_routing"
_HUNDRED: Final = Decimal(100)
#: Not suppliers a route can be moved onto.
_NOT_TARGETS: Final = frozenset({"manual", "inventory", "mock"})
#: Quarantine: failures in 24 h that start one, and its length by strike.
_STRIKE_THRESHOLD: Final = 3
_QUARANTINE_HOURS: Final = (6, 12, 24)
#: A task still running after this long counts as a failure for quarantine.
_HUNG_AFTER: Final = timedelta(minutes=30)
#: A price older than this is not used to choose (two hourly refreshes missed).
FRESH_FOR: Final = timedelta(hours=3)
#: A supplier this much cheaper than the route is suspect, not switched to.
SUSPICIOUS_DROP_PCT: Final = Decimal(30)
#: The live re-quote at switch time may come in this much above the stored price.
_VERIFY_SLACK_PCT: Final = Decimal(1)
#: A shadow proposal or a ``blocked`` line is logged once per this window.
_REPEAT_LOG_AFTER: Final = timedelta(hours=24)


@dataclass(frozen=True)
class Candidate:
    """One supplier for one SKU, as the job sees it.

    ``cost`` is the supplier's last good price and ``fresh`` whether it was
    confirmed within :data:`FRESH_FOR` — a price nobody could fetch for hours is
    not a reason to move anything. ``listed`` is false once the catalogue watch
    saw the supplier drop the position.
    """

    supplier: str
    cost: Decimal | None
    stock: int | None = None
    quarantined: bool = False
    fresh: bool = True
    listed: bool = True

    @property
    def cannot_sell(self) -> bool:
        """Known not to sell now — as opposed to merely not known."""
        return self.stock == 0 or self.quarantined or not self.listed

    @property
    def usable(self) -> bool:
        return self.cost is not None and self.fresh and not self.cannot_sell


@dataclass(frozen=True)
class Move:
    """What the job decided for one SKU: a target, or ``blocked`` with none."""

    reason: str  # cheaper | unavailable | blocked
    to: Candidate | None


def decide(
    current: str | None,
    candidates: list[Candidate],
    *,
    switch_pct: Decimal,
    stock_step_pct: Decimal,
    dwell_ok: bool,
) -> Move | None:
    """The move for one SKU, or ``None`` to stay. Pure — the rules in one place."""
    usable = sorted((c for c in candidates if c.usable), key=lambda c: (c.cost, c.supplier))
    cur = next((c for c in candidates if c.supplier == current), None) if current else None
    if cur is None:
        # A route this job knows nothing about (a supplier with no mapping, such
        # as a Steam rule on FoxReload): not its to move.
        return None
    if cur.cannot_sell:
        return _away_from(cur, usable, stock_step_pct=stock_step_pct)
    if not cur.usable or not usable or not dwell_ok:
        # No fresh price for the current route: nothing to compare — stay.
        return None
    return _cheaper(cur, usable[0], switch_pct=switch_pct)


def _cheaper(cur: Candidate, best: Candidate, *, switch_pct: Decimal) -> Move | None:
    """Both can sell: move when ``best`` is cheaper by the threshold and believable."""
    if best.supplier == cur.supplier or best.cost is None or cur.cost is None:
        return None
    if best.cost < cur.cost * (1 - SUSPICIOUS_DROP_PCT / _HUNDRED):
        # Far cheaper than any honest gap between suppliers: more likely a wrong
        # price (currency, pack size) than a bargain. A person looks.
        return Move("suspicious", None)
    if best.cost <= cur.cost * (1 - switch_pct / _HUNDRED):
        return Move("cheaper", best)
    return None


def _away_from(cur: Candidate, usable: list[Candidate], *, stock_step_pct: Decimal) -> Move:
    """The current supplier cannot sell: the cheapest that can, within the step."""
    if not usable:
        return Move("blocked", None)
    best = usable[0]
    too_dear = (
        cur.cost is not None
        and best.cost is not None
        and best.cost > cur.cost * (1 + stock_step_pct / _HUNDRED)
    )
    return Move("blocked", None) if too_dear else Move("unavailable", best)


@dataclass
class Report:
    """One run, for the scheduler log."""

    mode: str = "off"
    checked: int = 0
    moved: int = 0
    proposed: int = 0
    blocked: int = 0
    quarantined: int = 0
    errors: int = 0
    reasons: dict[str, int] = field(default_factory=dict)


async def run_smart_routing() -> Report:
    """One hourly pass. Each move commits on its own; a bad SKU never blocks the rest."""
    from yupay.modules.sourcing import settings as sourcing_settings

    report = Report()
    factory = get_session_factory()
    async with factory() as db:
        conf = await sourcing_settings.load(db)
        report.mode = conf.smart_mode
        if conf.smart_mode == "off":
            return report
        report.quarantined = await update_quarantine(db)
        await db.commit()
        rules = list(
            (
                await db.execute(
                    select(SkuSourcingRule).where(
                        SkuSourcingRule.managed.is_(True),
                        SkuSourcingRule.mode == "force_supplier",
                    )
                )
            )
            .scalars()
            .all()
        )
        if not rules:
            return report
        candidates = await _candidates(db, [r.sku_id for r in rules])
        recent = await _recent_log(
            db, [r.sku_id for r in rules], dwell_hours=conf.smart_dwell_hours
        )
        for rule in rules:
            report.checked += 1
            try:
                await _one(db, rule, candidates.get(rule.sku_id, []), recent, conf, report)
                await db.commit()
            except Exception as exc:  # one SKU's fault is logged, never the run's
                await db.rollback()
                report.errors += 1
                log.exception(
                    "sourcing.smart_routing.sku_failed",
                    sku_id=rule.sku_id,
                    error=type(exc).__name__,
                )
    return report


async def _one(
    db: AsyncSession,
    rule: SkuSourcingRule,
    candidates: list[Candidate],
    recent: dict[str, dict[str, Any]],
    conf: Any,
    report: Report,
) -> None:
    seen = recent.get(rule.sku_id, {})
    move = decide(
        rule.supplier_slug,
        candidates,
        switch_pct=conf.smart_switch_pct,
        stock_step_pct=conf.smart_stock_step_pct,
        dwell_ok=not seen.get("moved_recently", False),
    )
    if move is None:
        return
    report.reasons[move.reason] = report.reasons.get(move.reason, 0) + 1
    current = next((c for c in candidates if c.supplier == rule.supplier_slug), None)
    to_slug = move.to.supplier if move.to else None
    apply = conf.smart_mode == "on" and move.to is not None
    if not apply and (move.reason, to_slug) in seen.get("logged", set()):
        return  # proposed or blocked already, within the day
    log_row = SourcingSwitchLog(
        id=new_id(),
        sku_id=rule.sku_id,
        from_supplier=rule.supplier_slug,
        to_supplier=to_slug,
        from_cost_usdt=current.cost if current else None,
        to_cost_usdt=move.to.cost if move.to else None,
        reason=move.reason,
        applied=apply,
    )
    db.add(log_row)
    if move.to is None:
        report.blocked += 1
        return
    if not apply:
        report.proposed += 1
        return
    from yupay.modules.integrations.cost_refresh import refresh_routed_cost

    locked = await db.get(SkuSourcingRule, rule.sku_id, with_for_update=True)
    if locked is None or not locked.managed or locked.supplier_slug != rule.supplier_slug:
        return  # an operator touched it since the read: theirs wins
    problem: str | None = None
    async with db.begin_nested() as switch:
        locked.supplier_slug = move.to.supplier
        locked.updated_by = ACTOR
        locked.updated_at = now()
        await db.flush()
        # Re-priced live from the new supplier, as an operator's switch is. That
        # quote is also the check: the stored price may be up to three hours old.
        outcome = await refresh_routed_cost(db, sku_id=rule.sku_id)
        problem = _verify(outcome, expected=move.to.cost)
        if problem is not None:
            await switch.rollback()
    if problem is not None:
        await db.refresh(locked)
        log_row.applied = False
        log_row.reason = "verify_failed"
        report.reasons["verify_failed"] = report.reasons.get("verify_failed", 0) + 1
        log.info(
            "sourcing.smart_routing.verify_failed",
            sku_id=rule.sku_id,
            supplier=move.to.supplier,
            problem=problem,
        )
        return
    report.moved += 1
    log.info(
        "sourcing.smart_routing.moved",
        sku_id=rule.sku_id,
        reason=move.reason,
        from_supplier=rule.supplier_slug,
        to_supplier=move.to.supplier,
    )


def _verify(outcome: Any, *, expected: Decimal | None) -> str | None:
    """Why the live re-quote does not back the switch, or ``None`` when it does."""
    if outcome is None:
        return None  # nothing to check against (tests stub the re-price out)
    new_cost = getattr(outcome, "new_cost", None)
    if not getattr(outcome, "wrote_cost", False) or new_cost is None:
        return str(getattr(outcome, "reason", None) or "no live price")[:120]
    limit = expected * (1 + _VERIFY_SLACK_PCT / _HUNDRED) if expected is not None else None
    if limit is not None and Decimal(str(new_cost)) > limit:
        return f"live price {new_cost} above stored {expected}"
    return None


async def _candidates(db: AsyncSession, sku_ids: list[str]) -> dict[str, list[Candidate]]:
    """Every mapped supplier per SKU: last good price, its freshness, stock, state."""
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.integrations.models import CATALOG_DELISTED, SkuSupplierMapping
    from yupay.modules.sourcing.brand_overview import _stock_by_sku_supplier

    mappings = [
        m
        for m in (
            await db.execute(
                select(SkuSupplierMapping).where(
                    SkuSupplierMapping.sku_id.in_(sku_ids),
                    SkuSupplierMapping.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
        if m.supplier_slug in REGISTRY and m.supplier_slug not in _NOT_TARGETS
    ]
    # A delisted mapping stays a candidate that cannot sell: the route sitting on
    # it moves, and nothing moves onto it.
    delisted = {
        (m.sku_id, m.supplier_slug) for m in mappings if (m.extra or {}).get(CATALOG_DELISTED)
    }
    # The last good price per mapping and when it was confirmed: the price
    # refresh writes it every pass, moved or not (ADR-0108). History cannot
    # serve here — it records moves only, so "unchanged" and "unreachable for a
    # day" look the same in it.
    fresh_after = now() - FRESH_FOR
    prices: dict[tuple[str, str], tuple[Decimal | None, bool]] = {
        (str(sku), slug): (
            Decimal(cost) if cost is not None else None,
            checked is not None and checked > fresh_after,
        )
        for sku, slug, cost, checked in (
            await db.execute(
                text(
                    "SELECT sku_id, supplier_slug, cost_usdt, checked_at FROM supplier_price_state"
                    " WHERE sku_id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": sku_ids},
            )
        ).all()
    }
    stock = await _stock_by_sku_supplier(db, mappings)
    quarantined = {
        (q.sku_id, q.supplier_slug)
        for q in (
            await db.execute(
                select(SourcingQuarantine).where(
                    SourcingQuarantine.sku_id.in_(sku_ids), SourcingQuarantine.until > now()
                )
            )
        ).scalars()
    }
    out: dict[str, list[Candidate]] = {}
    for m in mappings:
        key = (m.sku_id, m.supplier_slug)
        cost, fresh = prices.get(key, (None, False))
        out.setdefault(m.sku_id, []).append(
            Candidate(
                supplier=m.supplier_slug,
                cost=cost,
                stock=stock.get(key, (None, None))[0],
                quarantined=key in quarantined,
                fresh=fresh,
                listed=key not in delisted,
            )
        )
    return out


async def _recent_log(
    db: AsyncSession, sku_ids: list[str], *, dwell_hours: int
) -> dict[str, dict[str, Any]]:
    """Per SKU: moved within the dwell, and what was already logged today."""
    moment = now()
    since = moment - max(_REPEAT_LOG_AFTER, timedelta(hours=dwell_hours))
    rows = (
        await db.execute(
            select(
                SourcingSwitchLog.sku_id,
                SourcingSwitchLog.reason,
                SourcingSwitchLog.to_supplier,
                SourcingSwitchLog.applied,
                SourcingSwitchLog.created_at,
            ).where(SourcingSwitchLog.sku_id.in_(sku_ids), SourcingSwitchLog.created_at > since)
        )
    ).all()
    out: dict[str, dict[str, Any]] = {}
    for sku_id, reason, to, applied, at in rows:
        entry = out.setdefault(sku_id, {"moved_recently": False, "logged": set()})
        if applied and at > moment - timedelta(hours=dwell_hours):
            entry["moved_recently"] = True
        if not applied and at > moment - _REPEAT_LOG_AFTER:
            entry["logged"].add((reason, to))
    return out


_FAILURES_SQL = text(
    """
    WITH f AS (
      SELECT oi.sku_id, t.supplier AS supplier_slug, t.created_at
      FROM fulfillment_tasks t JOIN order_items oi ON oi.id = t.order_item_id
      WHERE t.created_at > :since
        AND (t.status = 'failed' OR (t.status = 'in_progress' AND t.created_at < :hung))
      UNION ALL
      SELECT oi.sku_id, t.metadata->'auto_failover'->>'from', t.created_at
      FROM fulfillment_tasks t JOIN order_items oi ON oi.id = t.order_item_id
      WHERE t.created_at > :since AND t.metadata->'auto_failover'->>'to' IS NOT NULL
    )
    SELECT f.sku_id, f.supplier_slug, count(*), max(f.created_at)
    FROM f JOIN skus s ON s.id = f.sku_id
    WHERE NOT s.one_time_pack AND f.supplier_slug IS NOT NULL
    GROUP BY f.sku_id, f.supplier_slug
    """
)


async def update_quarantine(db: AsyncSession) -> int:
    """Start, extend or lift quarantines from the last day's failures; returns new ones.

    A one-time pack's refusal is the player's, not the supplier's, and is not counted.
    """
    moment = now()
    since = moment - timedelta(hours=24)
    failures = {
        (str(sku), slug): (int(n), last)
        for sku, slug, n, last in (
            await db.execute(_FAILURES_SQL, {"since": since, "hung": moment - _HUNG_AFTER})
        ).all()
    }
    existing = {
        (q.sku_id, q.supplier_slug): q
        for q in (await db.execute(select(SourcingQuarantine))).scalars().all()
    }
    started = 0
    for key, q in existing.items():
        if q.until > moment:
            continue
        n, last = failures.get(key, (0, None))
        if last is not None and last > q.until:
            # Failed again on its first orders back: a longer sit-out.
            q.strikes += 1
            q.until = moment + timedelta(hours=_hours(q.strikes))
            q.updated_at = moment
            started += 1
        elif await _succeeded_since(db, key, q.until):
            await db.delete(q)
    for key, (n, _last) in failures.items():
        if key in existing or n < _STRIKE_THRESHOLD:
            continue
        db.add(
            SourcingQuarantine(
                sku_id=key[0],
                supplier_slug=key[1],
                until=moment + timedelta(hours=_hours(1)),
                strikes=1,
                updated_at=moment,
            )
        )
        started += 1
    await db.flush()
    return started


def _hours(strikes: int) -> int:
    return _QUARANTINE_HOURS[min(strikes, len(_QUARANTINE_HOURS)) - 1]


async def _succeeded_since(db: AsyncSession, key: tuple[str, str], since: Any) -> bool:
    row = (
        await db.execute(
            text(
                "SELECT 1 FROM fulfillment_tasks t JOIN order_items oi ON oi.id = t.order_item_id"
                " WHERE oi.sku_id = CAST(:sku AS uuid) AND t.supplier = :slug"
                " AND t.status = 'succeeded' AND t.created_at > :since LIMIT 1"
            ),
            {"sku": key[0], "slug": key[1], "since": since},
        )
    ).first()
    return row is not None


async def recent_switches(db: AsyncSession, *, limit: int) -> list[Any]:
    """The admin list: newest first, each with its SKU's label."""
    from yupay.modules.catalog.admin_service import sku_labels_for
    from yupay.modules.sourcing.schemas import SourcingSwitchOut

    rows = list(
        (
            await db.execute(
                select(SourcingSwitchLog).order_by(SourcingSwitchLog.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    labels = await sku_labels_for(db, [r.sku_id for r in rows])
    out = []
    for r in rows:
        label = labels.get(r.sku_id)
        out.append(
            SourcingSwitchOut(
                sku_id=r.sku_id,
                sku_code=label.sku_code if label else None,
                label=" · ".join(p for p in (label.brand_name, label.denomination) if p)
                if label
                else None,
                from_supplier=r.from_supplier,
                to_supplier=r.to_supplier,
                from_cost_usdt=r.from_cost_usdt,
                to_cost_usdt=r.to_cost_usdt,
                reason=r.reason,
                applied=r.applied,
                created_at=r.created_at,
            )
        )
    return out


__all__ = [
    "Candidate",
    "Move",
    "Report",
    "decide",
    "recent_switches",
    "run_smart_routing",
    "update_quarantine",
]
