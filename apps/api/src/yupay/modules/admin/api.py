"""Public surface of the ``admin`` module.

This module is intentionally tiny — it owns the cross-cutting role gate and nothing
else. Each feature module (``catalog``, ``orders``, ``payments``, ...) defines its
own admin routes and depends on :func:`require_admin` from here.
"""

from yupay.modules.admin.deps import has_role, require_admin

__all__ = ["has_role", "require_admin"]
