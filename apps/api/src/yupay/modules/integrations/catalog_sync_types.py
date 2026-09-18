"""The report type every per-supplier catalogue sync returns.

Split into its own module so ``catalog_sync.py`` (the dispatcher) and
``catalog_sync_g2b.py`` / ``catalog_sync_nova.py`` / ``catalog_sync_gengine.py``
(one per supplier) can all import it without a cycle — the dispatcher needs
the three supplier modules, and the supplier modules need this type, so the
type cannot live in the dispatcher itself.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogSyncReport:
    """What one supplier's sync managed. ``error`` is advisory — a partial
    sync still counts.

    Field names are G2B's own vocabulary (it was the first and only supplier
    when they were named) but the shape is shared by every supplier this
    module knows how to sync:

    - ``vouchers``/``games`` are the top-level rows a full catalogue sweep
      wrote — flat, directly-mappable items for G2B's vouchers; game/service
      categories for everyone's ``game`` rows.
    - ``mapped_vouchers`` is whatever a supplier's sync does *beyond* the
      sweep for products/games we already hold an active mapping to — G2B
      re-reads each mapped voucher by id (see ``catalog_sync_g2b``); NOVA and
      G-Engine write ``game_denom`` rows for each mapped game's denominations
      (see ``catalog_sync_nova``/``catalog_sync_gengine``). Reused rather than
      renamed so the wire shape (``CatalogSyncOut``) does not have to grow a
      supplier-specific field.
    - ``missing_upstream`` counts mapped items the supplier no longer lists.
      The cached row is kept — the point is to flag it, not delete it out
      from under a mapping still pointing at it.
    """

    vouchers: int = 0
    games: int = 0
    mapped_vouchers: int = 0
    missing_upstream: int = 0
    error: str | None = None


__all__ = ["CatalogSyncReport"]
