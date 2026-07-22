"""Public interface for the ``uzum`` module.

Exposes the Merchant API :data:`router` (mounted in :mod:`yupay.api.v1`) and
the :class:`UzumTransaction` model, so callers depend on this surface rather
than reaching into ``routes``/``models`` directly.
"""

from __future__ import annotations

from yupay.modules.uzum.models import UzumTransaction
from yupay.modules.uzum.routes import router

__all__ = ["UzumTransaction", "router"]
