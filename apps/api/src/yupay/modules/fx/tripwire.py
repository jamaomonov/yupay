"""Apply an FX drop: page ops and put accepting providers into maintenance.

Recovery is manual — this module never flips a provider back to ``active``.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.logging import get_logger
from yupay.modules.fx.drop_detect import RateDrop
from yupay.modules.fx.refresh_cycle import refresh_and_detect_drops
from yupay.modules.notifications.api import schedule_after_commit, send_admin_alert
from yupay.modules.payments.provider_state import trip_active_to_maintenance

log = get_logger("yupay.fx.tripwire")


def _format_alert(drops: Sequence[RateDrop], changed: Sequence[str]) -> str:
    lines = ["<b>FX drop — платежи остановлены</b>"]
    for drop in drops:
        lines.append(
            f"USD→{drop.quote}: {drop.previous:.4f} → {drop.current:.4f} (−{drop.drop_pct:.1f}%)"
        )
    lines.append("В техработы: " + ", ".join(changed))
    lines.append("Включи провайдеров в админке → Провайдеры оплаты, когда курс стабилен.")
    return "\n".join(lines)


async def apply_drop_tripwire(db: AsyncSession, drops: Sequence[RateDrop]) -> list[str]:
    """If ``drops`` is non-empty, maintenance every currently-active provider.

    Already-``disabled`` rows stay disabled. Already-``maintenance`` rows are
    left alone and do not re-page ops. Returns the logical keys that changed.
    """
    if not drops:
        return []
    changed = await trip_active_to_maintenance(db)
    if not changed:
        log.info(
            "fx.tripwire.already_down",
            quotes=[d.quote for d in drops],
        )
        return []
    log.warning(
        "fx.tripwire.tripped",
        quotes=[d.quote for d in drops],
        providers=changed,
    )
    # Page ops only after the session commits. A later 503 on the admin
    # listing must not roll back maintenance *and* leave a "payments stopped"
    # message in the group (the listing and the trip used to share one txn).
    alert_text = _format_alert(drops, changed)
    schedule_after_commit(db, lambda: send_admin_alert(alert_text, kind="fx_drop"))
    return changed


async def refresh_and_trip(
    db: AsyncSession,
) -> tuple[list[RateDrop], list[str]]:
    """Refresh market rates, then trip providers if a watched quote dumped."""
    _current, drops = await refresh_and_detect_drops(db)
    tripped = await apply_drop_tripwire(db, drops)
    return drops, tripped


async def commit_refresh_and_trip(
    db: AsyncSession,
) -> tuple[list[RateDrop], list[str]]:
    """Same as :func:`refresh_and_trip`, then commit so a later listing 503
    cannot undo ``maintenance``. The ops alert fires on this commit.
    """
    drops, tripped = await refresh_and_trip(db)
    await db.commit()
    return drops, tripped
