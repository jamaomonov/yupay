"""Daily digest of SKUs whose shelf margin has drifted off its target.

The hourly cost refresh moves ``price_usd`` only **up** (``allow_price_drop=False``
in ``refresh_all_mappings``): when a supplier gets cheaper the margin widens and
the shelf price stays — a decision, not an accident («оставить цену, забрать
экономию», ADR-0081's sourcing-by-brand), so nothing here lowers a price. What
was missing was anyone being told. Measured on prod 2026-10-05, 130 active SKUs
sat more than 3 pp above their target margin, some for weeks, and no screen
listed them. This module lists them, once a day, to the admin alert chat.

Two buckets. **Above**: actual margin exceeds the target by more than
``settings.margin_drift_alert_pp`` — the operator decides per SKU whether to
keep the extra or cut the price. **Below**: actual margin is more than 1 pp
under the target — since retail rounds up (2026-10-05) that cannot come from
rounding any more, so a row here is a hand-set price, a cost that jumped past
a parked price, or a bug, and every one deserves a look.

Pure arithmetic in :func:`find_drift` and :func:`format_digest`, so the tests
need no Telegram; :func:`maybe_send_digest` adds the session, the 24-hour
dedupe and the send.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.notifications import api as notifications

log = get_logger(__name__)

_BELOW_PP = Decimal("1")
_DEDUPE_KEY = "alert:margin_drift_digest"
_DEDUPE_TTL = 24 * 3600
_TOP = 8


@dataclass(frozen=True)
class DriftRow:
    """One SKU whose actual margin is off its target."""

    brand_slug: str
    sku_code: str
    price_usd: Decimal
    cost_usdt: Decimal
    target_pct: Decimal
    actual_pct: Decimal

    @property
    def delta_pp(self) -> Decimal:
        """Actual minus target, in percentage points."""
        return self.actual_pct - self.target_pct


@dataclass(frozen=True)
class Drift:
    """What :func:`find_drift` found: the worst rows and the full counts."""

    above: list[DriftRow]
    below: list[DriftRow]
    above_total: int
    below_total: int

    @property
    def empty(self) -> bool:
        """Nothing to report."""
        return self.above_total == 0 and self.below_total == 0


async def find_drift(db: AsyncSession, *, above_pp: Decimal, top: int = _TOP) -> Drift:
    """Every active fixed-price SKU with a target margin, split by drift.

    Args:
        db: Session to read the catalogue with.
        above_pp: How far above target (percentage points) counts as drift.
        top: How many rows to keep per bucket, worst first.

    Returns:
        The drift, with the full counts and the ``top`` worst rows of each
        bucket. SKUs without a cost or a target margin are not drift — they
        are unpriced, which the cost refresh already reports.
    """
    rows = (
        await db.execute(
            select(Brand.slug, Sku.sku_code, Sku.price_usd, Sku.cost_usdt, Sku.margin_percent)
            .join(Product, Product.id == Sku.product_id)
            .join(Brand, Brand.id == Product.brand_id)
            .where(
                Sku.active.is_(True),
                Sku.variable_amount.is_(False),
                Sku.margin_percent.isnot(None),
                Sku.cost_usdt.isnot(None),
                Sku.cost_usdt > 0,
            )
        )
    ).all()
    above: list[DriftRow] = []
    below: list[DriftRow] = []
    for brand_slug, sku_code, price, cost, target in rows:
        actual = ((Decimal(price) / Decimal(cost)) - 1) * 100
        row = DriftRow(
            brand_slug=brand_slug,
            sku_code=sku_code,
            price_usd=Decimal(price),
            cost_usdt=Decimal(cost),
            target_pct=Decimal(target),
            actual_pct=actual.quantize(Decimal("0.1")),
        )
        if row.delta_pp > above_pp:
            above.append(row)
        elif row.delta_pp < -_BELOW_PP:
            below.append(row)
    above.sort(key=lambda r: r.delta_pp, reverse=True)
    below.sort(key=lambda r: r.delta_pp)
    return Drift(
        above=above[:top], below=below[:top], above_total=len(above), below_total=len(below)
    )


def _num(value: Decimal) -> str:
    """Plain digits, no exponent: ``Decimal("20.0000")`` prints ``20``, not ``2E+1``."""
    return f"{value.normalize():f}"


def _line(row: DriftRow) -> str:
    delta = row.delta_pp.quantize(Decimal("0.1"))
    sign = "+" if delta > 0 else ""
    return (
        f"• <code>{html.escape(row.brand_slug)}/{html.escape(row.sku_code)}</code> — "
        f"{_num(row.actual_pct)}% вместо {_num(row.target_pct)}% ({sign}{_num(delta)} пп), "
        f"${_num(row.price_usd)} при себестоимости ${_num(row.cost_usdt)}"
    )


def format_digest(drift: Drift, *, above_pp: Decimal) -> str:
    """The Telegram message, HTML. Counts first, then the worst rows."""
    parts = ["<b>📐 Маржа ушла от цели</b>"]
    if drift.below_total:
        parts.append(
            f"\n<b>Ниже цели</b> (больше чем на {_BELOW_PP} пп): {drift.below_total} SKU — "
            "это не округление, каждую стоит открыть."
        )
        parts.extend(_line(r) for r in drift.below)
    if drift.above_total:
        parts.append(
            f"\n<b>Выше цели</b> (больше чем на {above_pp.normalize()} пп): "
            f"{drift.above_total} SKU. Цена не снижается автоматически — "
            "решай по каждой: оставить или пересчитать (сохранить SKU в админке)."
        )
        parts.extend(_line(r) for r in drift.above)
    return "\n".join(parts)


async def maybe_send_digest() -> bool:
    """Send today's digest, if there is one and today's has not gone out.

    Called from the hourly refresh; the Redis dedupe keeps it to one message a
    day. Disabled by ``margin_drift_alert_pp <= 0``. Never raises.

    Returns:
        Whether a message was sent.
    """
    settings = get_settings()
    above_pp = Decimal(str(settings.margin_drift_alert_pp))
    if above_pp <= 0:
        return False
    from yupay.modules.fulfillment.service import _set_redis_dedupe

    try:
        async with get_session_factory()() as db:
            drift = await find_drift(db, above_pp=above_pp)
    except Exception as exc:  # noqa: BLE001 -- a digest must not break the refresh
        log.warning("integrations.margin_drift.failed", error=str(exc))
        return False
    if drift.empty:
        return False
    if await _set_redis_dedupe(_DEDUPE_KEY, ttl_seconds=_DEDUPE_TTL):
        return False
    return await notifications.send_admin_alert(
        format_digest(drift, above_pp=above_pp), kind="margin_drift"
    )


__all__ = ["Drift", "DriftRow", "find_drift", "format_digest", "maybe_send_digest"]
