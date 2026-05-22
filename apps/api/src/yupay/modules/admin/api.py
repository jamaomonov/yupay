"""Public surface of the ``admin`` module.

Owns the cross-cutting role gate plus a small set of admin-wide aggregate routes
(global search, eventually customer-360). Feature modules (``catalog``, ``orders``,
``payments``, …) still define their own admin routes and depend on
:func:`require_admin` from here.
"""

from yupay.modules.admin.deps import has_role, require_admin
from yupay.modules.admin.routes import admin_router

__all__ = ["admin_router", "has_role", "require_admin"]
