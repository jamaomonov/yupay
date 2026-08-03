"""Analytics aggregate services (business + ops tabs).

Split out of ``service.py`` to keep each file under the size budget, and
further split here (business vs. ops) once the combined module outgrew its
own budget. Shares the dashboard's stuck-payment / low-stock helpers and
constants — those stay canonical in ``service.py`` and are imported from
``ops.py`` (see ``ops.py`` docstring and the bottom of ``service.py`` for the
re-export that keeps existing references working).
"""

from __future__ import annotations

from yupay.modules.stats.analytics.business import build_business_analytics
from yupay.modules.stats.analytics.ops import build_ops_analytics

__all__ = ["build_business_analytics", "build_ops_analytics"]
