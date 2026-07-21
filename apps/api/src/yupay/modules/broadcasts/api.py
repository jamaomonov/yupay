"""Public surface of the ``broadcasts`` module.

Exposes the admin router for the ``api/v1`` mount plus the ORM models other modules
may need to reference (e.g. an admin aggregate view).

The (later-task) scheduler dispatch job imports ``broadcasts.service`` directly rather
than going through this module, to avoid an ``api`` -> ``routes`` -> ``api/v1`` import
cycle (``routes.py`` pulls in ``yupay.api.v1.deps``, which the scheduler process does
not otherwise need).
"""

from __future__ import annotations

from yupay.modules.broadcasts.models import Broadcast, BroadcastRecipient
from yupay.modules.broadcasts.routes import admin_router

__all__ = ["Broadcast", "BroadcastRecipient", "admin_router"]
