"""Dispatch a supplier catalogue sync to that supplier's own module.

Originally one file (``sync_g2b_catalog`` plus the mapped-voucher refresh it
called). NOVA and G-Engine joining the sync would have pushed a single
branchy module well past AGENTS.md §6's 400-LOC soft limit, and each
supplier's catalogue shape is different enough (G2B: flat vouchers + games;
NOVA: games + a per-game offers call; G-Engine: games with denominations
embedded inline) that one function per supplier reads better than a shared
one with three special cases. So this module is now just the shared report
type's home (re-exported from ``catalog_sync_types``) and a thin dispatcher;
the actual work is one module per supplier — see ``catalog_sync_g2b.py``,
``catalog_sync_nova.py``, ``catalog_sync_gengine.py`` — the same split
``sourcing/brand_overview.py`` and ``integrations/cost_lookup.py`` used on
this same branch.

``sync_g2b_catalog`` stays importable from here (re-exported) for whichever
caller still names it directly; new callers should prefer
:func:`run_catalog_sync`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol

from yupay.core.errors import NotFoundError
from yupay.modules.integrations.catalog_sync_g2b import sync_g2b_catalog
from yupay.modules.integrations.catalog_sync_gengine import (
    sync_gengine_catalog,
    sync_gengine_game_denominations,
    sync_gengine_voucher_denominations,
)
from yupay.modules.integrations.catalog_sync_nova import (
    sync_nova_catalog,
    sync_nova_game_denominations,
    sync_nova_voucher_denominations,
)
from yupay.modules.integrations.catalog_sync_types import CatalogSyncReport

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class _DenomSyncer(Protocol):
    """One supplier's on-demand denomination syncer.

    A plain ``Callable[..., Awaitable[tuple[int, str | None]]]`` erases the
    keyword-only ``game_id`` both :func:`~catalog_sync_nova.sync_nova_game_denominations`
    and :func:`~catalog_sync_gengine.sync_gengine_game_denominations` share, so
    ``mypy --strict`` cannot check the ``game_id=game_id`` call in
    :func:`run_game_denomination_sync` below against it. This restores the
    signature so that call is actually checked.
    """

    def __call__(self, db: AsyncSession, *, game_id: str) -> Awaitable[tuple[int, str | None]]: ...


class _VoucherDenomSyncer(Protocol):
    """The same shape for a *voucher's* ladder — a NOVA gift-card category or
    a G-Engine shop product — which is a different catalogue with a different
    endpoint, not the same call with another id."""

    def __call__(
        self, db: AsyncSession, *, product_id: str
    ) -> Awaitable[tuple[int, str | None]]: ...


#: Suppliers a full catalogue sweep is wired up for. Mirrors
#: ``routes._KNOWN_SUPPLIERS`` minus Waxpeer, which sells Steam items by
#: login rather than a browsable catalogue and so has nothing to sync.
SYNCABLE_SUPPLIERS: frozenset[str] = frozenset({"g2b", "nova", "gengine"})

#: Suppliers the on-demand single-game denomination sync supports. G2B is
#: deliberately not here — its per-game denomination picker already exists as
#: a live GET (``/g2b/games/{game_code}/catalogue``, pre-dating this branch)
#: and was not moved into the cache; see ``catalog_sync_gengine``'s module
#: docstring for the shop-catalogue scope note this mirrors.
DENOM_SYNCABLE_SUPPLIERS: frozenset[str] = frozenset({"nova", "gengine"})

_SYNCERS: dict[str, Callable[[AsyncSession], Awaitable[CatalogSyncReport]]] = {
    "g2b": sync_g2b_catalog,
    "nova": sync_nova_catalog,
    "gengine": sync_gengine_catalog,
}

_DENOM_SYNCERS: dict[str, _DenomSyncer] = {
    "nova": sync_nova_game_denominations,
    "gengine": sync_gengine_game_denominations,
}

_VOUCHER_DENOM_SYNCERS: dict[str, _VoucherDenomSyncer] = {
    "nova": sync_nova_voucher_denominations,
    "gengine": sync_gengine_voucher_denominations,
}


async def run_catalog_sync(db: AsyncSession, *, supplier_slug: str) -> CatalogSyncReport:
    """Refresh one supplier's half of ``supplier_catalog_cache``.

    Each per-supplier sync is best-effort by design (a supplier hiccup must
    not raise past this call — see the per-supplier modules), so the only way
    this itself raises is an unknown ``supplier_slug``, which the route layer
    should already have refused via a ``Literal`` path type before reaching
    here. The caller commits.
    """
    try:
        syncer = _SYNCERS[supplier_slug]
    except KeyError:
        raise NotFoundError(f"no catalogue sync for supplier {supplier_slug!r}") from None
    return await syncer(db)


async def run_game_denomination_sync(
    db: AsyncSession, *, supplier_slug: str, game_id: str
) -> tuple[int, str | None]:
    """Pull one game's denominations into the cache, on demand.

    See :data:`DENOM_SYNCABLE_SUPPLIERS` for which suppliers this covers and
    why G2B is not one of them.
    """
    try:
        syncer = _DENOM_SYNCERS[supplier_slug]
    except KeyError:
        raise NotFoundError(f"no denomination sync for supplier {supplier_slug!r}") from None
    return await syncer(db, game_id=game_id)


async def run_voucher_denomination_sync(
    db: AsyncSession, *, supplier_slug: str, product_id: str
) -> tuple[int, str | None]:
    """Pull one voucher product's ladder into the cache, on demand.

    Same suppliers as :data:`DENOM_SYNCABLE_SUPPLIERS`, and G2B is absent for
    a different reason than it is there: a G2B voucher genuinely is flat —
    one product, one price — so it has no ladder to pull.
    """
    try:
        syncer = _VOUCHER_DENOM_SYNCERS[supplier_slug]
    except KeyError:
        raise NotFoundError(
            f"no voucher denomination sync for supplier {supplier_slug!r}"
        ) from None
    return await syncer(db, product_id=product_id)


__all__ = [
    "DENOM_SYNCABLE_SUPPLIERS",
    "SYNCABLE_SUPPLIERS",
    "CatalogSyncReport",
    "run_catalog_sync",
    "run_game_denomination_sync",
    "run_voucher_denomination_sync",
    "sync_g2b_catalog",
]
