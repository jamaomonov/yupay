"""Public interface for the ``click`` module.

Exposes the Shop API :data:`router` (mounted in :mod:`yupay.api.v1`) and the
:class:`ClickTransaction` model, so callers depend on this surface rather
than reaching into ``routes``/``models`` directly.
"""

from __future__ import annotations

from yupay.modules.click.models import ClickTransaction
from yupay.modules.click.routes import router

__all__ = ["ClickTransaction", "router"]
