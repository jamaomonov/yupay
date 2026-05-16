"""Single source of truth for "now".

All code that needs the current time should call :pyfunc:`now` instead of
``datetime.now()`` directly. This makes tests deterministic via :pyfunc:`set_clock`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

_clock: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731


def now() -> datetime:
    """Return the current UTC datetime."""
    return _clock()


def set_clock(fn: Callable[[], datetime]) -> None:
    """Override the clock (for tests)."""
    global _clock
    _clock = fn


def reset_clock() -> None:
    """Restore the default clock."""
    global _clock
    _clock = lambda: datetime.now(UTC)  # noqa: E731
