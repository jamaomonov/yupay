"""Shared bits between the business and ops analytics halves.

Kept intentionally tiny — anything used by only one half stays in that
half's file (``business.py`` / ``ops.py``).
"""

from __future__ import annotations

_PAID_LIKE = ("paid", "fulfilling", "fulfilled", "delivered")
