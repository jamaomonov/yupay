"""Public interface for the ``payme`` module.

Exposes the Merchant API JSON-RPC :data:`router` (mounted in
:mod:`yupay.api.v1`) and the :class:`PaymeTransaction` model, so callers depend
on this surface rather than reaching into ``routes``/``models`` directly.
"""

from __future__ import annotations

from yupay.modules.payme.models import PaymeTransaction
from yupay.modules.payme.routes import router

__all__ = ["PaymeTransaction", "router"]
