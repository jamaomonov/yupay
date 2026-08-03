"""Admin-facing summaries and mutations over :mod:`payments.provider_state`.

Split out of ``service.py`` (already near its LOC limit) rather than folded
in. Two small functions: ``list_admin_providers`` groups the registry +
``payment_provider_states`` rows into one row per logical provider, and
``set_provider_state`` writes a new state and returns the refreshed summary.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.payments import provider_state
from yupay.modules.payments.gateways import REGISTRY
from yupay.modules.payments.provider_state import ProviderState
from yupay.modules.payments.schemas import AdminProviderSummary


async def list_admin_providers(db: AsyncSession) -> list[AdminProviderSummary]:
    """One summary per logical provider (config-availability = any slug has keys)."""
    summaries: list[AdminProviderSummary] = []
    for logical, lp in provider_state.LOGICAL_PROVIDERS.items():
        states = await provider_state.get_states(db, lp.slugs)
        rows = await provider_state.get_state_rows(db, lp.slugs)
        config_available = any(
            (gw := REGISTRY.get(s)) is not None and gw.available for s in lp.slugs
        )
        # The group's state is uniform (we always write all slugs together); take
        # the first slug's state as canonical, plus its changed_by/at.
        canonical = rows.get(lp.slugs[0])
        summaries.append(
            AdminProviderSummary(
                provider=logical,
                display_name=lp.display_name,
                slugs=lp.slugs,
                config_available=config_available,
                state=states[lp.slugs[0]],
                changed_by=canonical.changed_by if canonical else None,
                changed_at=canonical.changed_at if canonical else None,
            )
        )
    return summaries


async def set_provider_state(
    db: AsyncSession, *, provider: str, state: ProviderState, changed_by: str | None
) -> AdminProviderSummary:
    """Set every slug of ``provider``'s group to ``state`` and return the summary.

    Raises:
        NotFoundError: ``provider`` is not a known logical provider (propagated
            from :func:`provider_state.set_logical_state`).
    """
    await provider_state.set_logical_state(
        db, provider=provider, state=state, changed_by=changed_by
    )
    await db.flush()
    summaries = await list_admin_providers(db)
    return next(s for s in summaries if s.provider == provider)


__all__ = ["list_admin_providers", "set_provider_state"]
