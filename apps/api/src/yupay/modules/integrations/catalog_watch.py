"""Watch the supplier catalogue for positions we map that the supplier
delisted — deactivate the SKU and tell a human.

A supplier can drop a catalogue entry at any moment and for no stated reason:
a weekly promo pack rotates out, a «(discounted)» variant expires, a voucher
is withdrawn. Until this module, the first anyone heard of it was a customer's
order failing at fulfilment. Now the hourly tick compares every ACTIVE
mapping against the live catalogue:

* game mappings — ``external_variant_id`` against ``games_catalogue`` names,
  one supplier call per distinct game;
* voucher mappings — ``fetch_product`` by id (``None`` is the supplier's own
  explicit "not listed", distinct from an error).

**Two-strike rule.** A miss never acts immediately: the first one stamps
``extra["catalog_missing_since"]`` on the mapping; a later tick that still
misses — at least ``_CONFIRM_AFTER`` after the stamp — deactivates the SKU
and sends one Telegram alert. A fetch error or an EMPTY catalogue skips the
game entirely, stamping nothing: a supplier outage that mass-deactivated the
shelf would be worse than the problem this solves.

The mapping row itself stays active — it is the watch's memory. If the
position reappears, a pending stamp is cleared quietly; after a deactivation
the admin gets a "it's back" alert but the SKU stays off until a human
re-checks the price and re-enables it (the admin SKU card).

Per-supplier by construction: the loop asks the fulfiller registry for each
supplier that has active mappings and skips those without a catalogue client.
Today that is G2B; adding another supplier is a registry entry, not new code
here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.logging import get_logger
from yupay.modules.catalog.models import Sku
from yupay.modules.integrations.models import SkuSupplierMapping

log = get_logger("yupay.integrations.catalog_watch")

#: Minimum stamp age before the second strike may act. One hourly cadence
#: minus scheduling jitter: the confirming look is a genuinely later tick,
#: not the same incident observed twice.
_CONFIRM_AFTER = timedelta(minutes=45)

_STAMP = "catalog_missing_since"
_ACTED = "catalog_watch_deactivated"


class CatalogClient(Protocol):
    """The two supplier calls the watch needs; G2bClient satisfies it."""

    async def games_catalogue(self, game_code: str) -> list[dict[str, Any]]: ...

    async def fetch_product(self, product_id: str) -> dict[str, Any] | None: ...


SendAlert = Callable[..., Awaitable[bool]]


@dataclass(frozen=True)
class CatalogWatchReport:
    """One tick's outcome, for the scheduler log line."""

    checked: int = 0
    stamped: int = 0
    deactivated: int = 0
    reappeared: int = 0
    skipped_games: int = 0


def _stamp_age(mapping: SkuSupplierMapping) -> timedelta | None:
    raw = mapping.extra.get(_STAMP)
    if not isinstance(raw, str):
        return None
    try:
        return now() - datetime.fromisoformat(raw)
    except ValueError:
        return None


async def _handle_missing(
    mapping: SkuSupplierMapping,
    sku: Sku,
    *,
    position: str,
    send_alert: SendAlert,
) -> tuple[int, int]:
    """One mapping whose position the supplier no longer lists.

    Returns ``(stamped, deactivated)`` increments.
    """
    if mapping.extra.get(_ACTED):
        return 0, 0
    age = _stamp_age(mapping)
    if age is None:
        mapping.extra = {**mapping.extra, _STAMP: now().isoformat()}
        log.warning(
            "integrations.catalog_watch.missing_stamped",
            supplier=mapping.supplier_slug,
            sku_code=sku.sku_code,
        )
        return 1, 0
    if age < _CONFIRM_AFTER:
        return 0, 0
    sku.active = False
    mapping.extra = {**mapping.extra, _ACTED: True}
    log.warning(
        "integrations.catalog_watch.sku_deactivated",
        supplier=mapping.supplier_slug,
        sku_code=sku.sku_code,
    )
    await send_alert(
        (
            f"🗑 Поставщик {mapping.supplier_slug} убрал из каталога «{position}».\n"
            f"SKU {sku.sku_code} деактивирован и снят с витрины.\n"
            "Маппинг сохранён — если позиция вернётся, придёт отдельное уведомление."
        ),
        kind="catalog_watch",
    )
    return 0, 1


async def _handle_present(
    mapping: SkuSupplierMapping,
    sku: Sku,
    *,
    position: str,
    send_alert: SendAlert,
) -> int:
    """The position is (still or again) listed. Returns the reappeared increment."""
    if mapping.extra.get(_ACTED):
        mapping.extra = {k: v for k, v in mapping.extra.items() if k not in (_STAMP, _ACTED)}
        log.info(
            "integrations.catalog_watch.position_reappeared",
            supplier=mapping.supplier_slug,
            sku_code=sku.sku_code,
        )
        await send_alert(
            (
                f"↩️ Позиция «{position}» снова в каталоге {mapping.supplier_slug}.\n"
                f"SKU {sku.sku_code} остаётся выключенным — проверьте цену и включите "
                "вручную в админке."
            ),
            kind="catalog_watch",
        )
        return 1
    if _STAMP in mapping.extra:
        mapping.extra = {k: v for k, v in mapping.extra.items() if k != _STAMP}
    return 0


async def _active_mappings(
    db: AsyncSession, *, supplier_slug: str, kind: str
) -> list[tuple[SkuSupplierMapping, Sku]]:
    rows = await db.execute(
        select(SkuSupplierMapping, Sku)
        .join(Sku, Sku.id == SkuSupplierMapping.sku_id)
        .where(
            SkuSupplierMapping.supplier_slug == supplier_slug,
            SkuSupplierMapping.kind == kind,
            SkuSupplierMapping.is_active.is_(True),
        )
        .order_by(Sku.sku_code)
    )
    return [(m, s) for m, s in rows.all()]


async def watch_mapped_variants(
    db: AsyncSession,
    *,
    client: CatalogClient,
    send_alert: SendAlert,
    supplier_slug: str = "g2b",
) -> CatalogWatchReport:
    """One watch tick for one supplier. Flushes; the caller commits."""
    checked = stamped = deactivated = reappeared = skipped_games = 0

    # --- game mappings: one catalogue call per distinct game ---------------
    game_rows = await _active_mappings(db, supplier_slug=supplier_slug, kind="game")
    by_game: dict[str, list[tuple[SkuSupplierMapping, Sku]]] = {}
    for mapping, sku in game_rows:
        by_game.setdefault(mapping.external_product_id, []).append((mapping, sku))

    for game_code, pairs in by_game.items():
        try:
            catalogue = await client.games_catalogue(game_code)
        except Exception as exc:  # noqa: BLE001 -- an outage must not stamp anything
            skipped_games += 1
            log.warning(
                "integrations.catalog_watch.game_fetch_failed",
                game_code=game_code,
                error=str(exc)[:200],
            )
            continue
        names = {
            str(row.get("name") or row.get("catalogue_name") or "").strip() for row in catalogue
        }
        names.discard("")
        if not names:
            # A game we actively map selling zero positions reads as an outage
            # or an API change, not as "everything was delisted at once".
            skipped_games += 1
            log.warning("integrations.catalog_watch.game_catalogue_empty", game_code=game_code)
            continue
        for mapping, sku in pairs:
            checked += 1
            position = mapping.external_variant_id or mapping.external_product_id
            if mapping.external_variant_id and mapping.external_variant_id not in names:
                s, d = await _handle_missing(mapping, sku, position=position, send_alert=send_alert)
                stamped += s
                deactivated += d
            else:
                reappeared += await _handle_present(
                    mapping, sku, position=position, send_alert=send_alert
                )

    # --- voucher mappings: by-id fetch; None is an explicit "not listed" ---
    for mapping, sku in await _active_mappings(db, supplier_slug=supplier_slug, kind="voucher"):
        checked += 1
        try:
            item = await client.fetch_product(mapping.external_product_id)
        except Exception as exc:  # noqa: BLE001 -- an error is not a delisting
            log.warning(
                "integrations.catalog_watch.voucher_fetch_failed",
                product_id=mapping.external_product_id,
                error=str(exc)[:200],
            )
            continue
        if item is None:
            s, d = await _handle_missing(
                mapping, sku, position=mapping.external_product_id, send_alert=send_alert
            )
            stamped += s
            deactivated += d
        else:
            reappeared += await _handle_present(
                mapping, sku, position=mapping.external_product_id, send_alert=send_alert
            )

    await db.flush()
    return CatalogWatchReport(
        checked=checked,
        stamped=stamped,
        deactivated=deactivated,
        reappeared=reappeared,
        skipped_games=skipped_games,
    )


__all__ = ["CatalogClient", "CatalogWatchReport", "watch_mapped_variants"]
