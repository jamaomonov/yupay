"""Shared cost-refresh runner for every active supplier mapping.

Invoked from two places:

- The hourly scheduler job
  (``apps/scheduler/.../jobs/refresh_supplier_prices.py``).
- The on-demand admin button (``POST /admin/integrations/refresh-all-prices``).

Both are the *automatic* path: nobody typed a number, the run just re-pulls
whatever the supplier is quoting today. So every call into
``svc.refresh_sku_cost_for_mapping`` below passes ``allow_price_drop=False``
— a cost drop still updates ``Sku.cost_usdt``, but the margin-derived price
is left alone rather than quietly handed to the customer as a lower shelf
price. A cost rise still raises it. See ``catalog.admin_service.
set_sku_cost_usdt`` for the rule and why an operator editing a mapping by
hand (``integrations.routes._refresh_sku_cost``) keeps the opposite default.

Each mapping is processed in its own transaction so a single failure
doesn't roll back the rest. Price moves that cross
``settings.price_alert_threshold_pct`` trigger a Telegram alert via the
separate admin bot (``notifications.send_admin_alert``).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.integrations import service as svc
from yupay.modules.integrations.models import NOVA_STEAM_SENTINEL
from yupay.modules.notifications import api as notifications

if TYPE_CHECKING:
    from yupay.modules.integrations.models import SkuSupplierMapping

log = get_logger("yupay.integrations.price_refresh")


@dataclass(frozen=True)
class PriceRefreshReport:
    """Aggregate result returned to whoever triggered the run."""

    checked: int = 0
    moved: int = 0
    alerts_sent: int = 0
    errors: int = 0


async def _fetch_nova_offers_cache(
    mappings: list[SkuSupplierMapping],
) -> dict[str, dict[str, Any]]:
    """Fetch every distinct NOVA category's ``get_offers()`` exactly once.

    Nineteen Free Fire SKUs mapped to the same NOVA category used to mean
    nineteen ``GET /topups/offers`` calls, one per mapping, each made
    inside that mapping's own open transaction with a 20-second timeout
    and no retry — the kind of pattern that gets an integration
    rate-limited. Grouping by category fixes both problems: one call per
    category, made before any per-mapping transaction opens rather than
    inside one.

    Keyed on the *stripped* ``external_product_id`` — the same
    normalisation :func:`_nova_raw_price` applies before checking the
    cache — so every mapping in a category actually hits it instead of
    silently missing and falling back to its own live call. Only NOVA
    mappings are considered; ``g2b`` ignores this cache entirely. The
    Steam sentinel has no catalogue to fetch and is excluded up front.

    A category whose fetch fails is simply left out of the returned map:
    :func:`_nova_raw_price` treats a cache miss as "fetch it live", so one
    bad category degrades to its old per-mapping behaviour instead of
    failing the whole run.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.nova import NovaFulfiller

    fulfiller = REGISTRY.get("nova")
    if not isinstance(fulfiller, NovaFulfiller) or not fulfiller.available:
        return {}

    category_ids: set[str] = set()
    for mapping in mappings:
        if mapping.supplier_slug != "nova":
            continue
        category_id = mapping.external_product_id.strip()
        if category_id and category_id != NOVA_STEAM_SENTINEL:
            category_ids.add(category_id)

    cache: dict[str, dict[str, Any]] = {}
    client = fulfiller._client()
    for category_id in category_ids:
        try:
            cache[category_id] = await client.get_offers(category_id)
        except Exception as exc:  # noqa: BLE001 -- best effort; a miss falls back to a live per-mapping call
            log.warning(
                "integrations.price_refresh.category_fetch_failed",
                category_id=category_id,
                error=str(exc),
            )
    return cache


async def refresh_all_mappings(*, supplier_slug: str | None = None) -> PriceRefreshReport:
    """Re-price every active mapping and dispatch alerts on significant moves.

    Uses its own session per mapping — a runtime error refreshing one
    SKU never blocks the rest of the queue. Returns a per-run summary
    the admin button echoes back to the UI.

    Passes ``allow_price_drop=False`` to every refresh: this runner is the
    automatic path (hourly tick or the on-demand "refresh all" button, not
    an operator editing one mapping by hand), so a cost drop widens the
    margin instead of silently lowering the shelf price. See
    ``catalog.admin_service.set_sku_cost_usdt``.
    """
    factory = get_session_factory()
    threshold = float(get_settings().price_alert_threshold_pct)

    # Snapshot the mapping list up-front in a quick read-only session so
    # the iteration doesn't hold a long transaction.
    async with factory() as session:
        mappings = await svc.list_active_mappings(session, supplier_slug=supplier_slug)

    if not mappings:
        return PriceRefreshReport()

    # One fetch per NOVA category, done up front — before any per-mapping
    # transaction is even open — instead of once per mapping.
    nova_offers_cache = await _fetch_nova_offers_cache(mappings)

    checked = 0
    moved = 0
    alerts = 0
    errors = 0

    for mapping in mappings:
        checked += 1
        try:
            async with factory() as session, session.begin():
                # ``mapping`` is detached after the snapshot session
                # closed; merge brings it back into this session so
                # the FK lookups inside refresh work.
                attached = await session.merge(mapping)
                outcome = await svc.refresh_sku_cost_for_mapping(
                    session,
                    mapping=attached,
                    nova_offers_cache=nova_offers_cache,
                    allow_price_drop=False,
                )
        except Exception as exc:  # noqa: BLE001
            errors += 1
            log.warning(
                "integrations.price_refresh.iteration_failed",
                sku_id=mapping.sku_id,
                error=str(exc),
            )
            continue

        if not outcome.updated or outcome.new_cost is None:
            continue
        moved += 1
        if await _should_alert(outcome.old_cost, outcome.new_cost, threshold):
            text = _format_alert(mapping=mapping, outcome=outcome)
            if await notifications.send_admin_alert(text, kind="price_change"):
                alerts += 1

    # Proactive low-balance warning. Independent of whether any
    # mapping moved this tick — supplier could be sub-threshold even
    # when prices are stable.
    await _maybe_warn_low_balance()

    log.info(
        "integrations.price_refresh.done",
        checked=checked,
        moved=moved,
        alerts_sent=alerts,
        errors=errors,
    )
    return PriceRefreshReport(checked=checked, moved=moved, alerts_sent=alerts, errors=errors)


async def _maybe_warn_low_balance() -> None:  # noqa: PLR0911 -- discriminated short-circuits
    """Ping ops when G2B's wallet is dangerously low — before an order
    actually rejects.

    Distinct from the per-order ``supplier_low_balance`` alert: that one
    fires only when a real customer order gets rejected; this one is a
    pre-emptive heads-up. Both reuse ``send_admin_alert`` but each owns
    a separate Redis dedupe key.
    """
    settings = get_settings()
    threshold = float(settings.supplier_low_balance_threshold)
    if threshold <= 0:
        return
    from yupay.modules.fulfillment.service import _set_redis_dedupe
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.g2b import G2bFulfiller

    fulfiller = REGISTRY.get("g2b")
    if not isinstance(fulfiller, G2bFulfiller) or not fulfiller.available:
        return
    try:
        me = await fulfiller._client().get_me()
    except Exception as exc:  # noqa: BLE001
        log.warning("integrations.lowbal.getme_failed", error=str(exc))
        return
    raw_balance = me.get("balance")
    if raw_balance is None:
        return
    try:
        balance = float(raw_balance)
    except (TypeError, ValueError):
        return
    if balance >= threshold:
        return
    # 6h dedupe so we don't ping ops on every hourly tick while the
    # wallet stays below threshold overnight.
    if await _set_redis_dedupe("alert:low_balance_warn:g2b", ttl_seconds=6 * 3600):
        return
    text = (
        "<b>ℹ️ Баланс G2B заканчивается</b>\n"
        f"Текущий баланс: <b>${balance:.2f}</b>\n"
        f"Порог: <b>${threshold:.2f}</b>\n"
        "Пополни счёт у G2B заранее, чтобы клиенты не зависли в «обработке»."
    )
    await notifications.send_admin_alert(text, kind="supplier_balance_low")


async def _should_alert(
    old_cost: Decimal | None, new_cost: Decimal | None, threshold_pct: float
) -> bool:
    """Whether the move from ``old_cost`` to ``new_cost`` deserves an alert.

    First-time pricing (``old_cost`` is ``None``) always alerts so ops
    sees the initial cost. Otherwise we apply the symmetric percentage
    threshold from settings.
    """
    if new_cost is None:
        return False
    if old_cost is None:
        return True
    if old_cost <= 0:
        return True
    delta_pct = abs((new_cost - old_cost) / old_cost) * Decimal("100")
    return float(delta_pct) >= threshold_pct


def _format_alert(*, mapping: object, outcome: object) -> str:
    """Build the HTML body sent to the ops Telegram channel.

    Kept here (rather than in the alerts module) because the content is
    integration-specific. Strings are short and bullet-y on purpose —
    Telegram renders large blocks poorly on mobile.
    """
    sku_id = getattr(mapping, "sku_id", "?")
    # supplier/ext_id/variant are supplier- or admin-entered free text (mapping
    # fields) — escape before splicing into a parse_mode:HTML message.
    supplier = html.escape(str(getattr(mapping, "supplier_slug", "?")))
    kind = getattr(mapping, "kind", "?")
    ext_id = html.escape(str(getattr(mapping, "external_product_id", "?")))
    variant = getattr(mapping, "external_variant_id", None)
    old = getattr(outcome, "old_cost", None)
    new = getattr(outcome, "new_cost", None)

    # Explicit direction in words, not just a sign an operator can miss
    # skimming on a phone: "cost moved 3.6%" alone doesn't say whether that
    # was a saving or a squeeze.
    delta_line = ""
    if old is not None and new is not None and old not in (0, Decimal("0")):
        delta = (Decimal(str(new)) - Decimal(str(old))) / Decimal(str(old)) * Decimal("100")
        if delta > 0:
            sign, direction = "+", "выросла"
        elif delta < 0:
            sign, direction = "", "снизилась"
        else:
            sign, direction = "", "не изменилась"
        delta_line = f"\n<i>Себестоимость {direction}: {sign}{delta:.2f}%</i>"

    variant_line = f" · <code>{html.escape(str(variant))}</code>" if variant else ""
    old_str = f"${old}" if old is not None else "—"

    # Present when the SKU had a saved margin *and* the re-derived price was
    # actually written — see CostRefreshOutcome / set_sku_cost_usdt. A SKU
    # with no margin on file gets no price line, same as it got no price
    # change. A margin that *would* have lowered the price, refused by
    # allow_price_drop=False, gets its own line instead — otherwise it reads
    # identically to "no margin at all", and an operator can't tell a
    # deliberate save from an unrelated SKU.
    old_price = getattr(outcome, "old_price", None)
    new_price = getattr(outcome, "new_price", None)
    margin = getattr(outcome, "margin_percent", None)
    price_drop_blocked = bool(getattr(outcome, "price_drop_blocked", False))
    price_line = ""
    if new_price is not None:
        price_line = f"\nЦена USD: ${old_price} → <b>${new_price}</b> (наценка {margin}% сохранена)"
    elif price_drop_blocked:
        # Reachable only on a cost *drop* — `set_sku_cost_usdt` no longer sets
        # the flag on a rise, precisely so this sentence cannot appear under a
        # line saying the cost went up.
        price_line = (
            "\nЦена USD: <b>не снижена</b> — при автоматической синхронизации "
            "цена не опускается, себестоимость обновлена, наценка выросла"
        )

    return (
        f"<b>💰 Цена поставщика изменилась</b>\n"
        f"Поставщик: <code>{supplier}</code> · <code>{kind}</code>\n"
        f"Продукт: <code>{ext_id}</code>{variant_line}\n"
        f"SKU: <code>{sku_id}</code>\n"
        f"Было: {old_str} → Стало: <b>${new}</b>"
        f"{delta_line}"
        f"{price_line}"
    )


__all__ = ["PriceRefreshReport", "refresh_all_mappings"]
