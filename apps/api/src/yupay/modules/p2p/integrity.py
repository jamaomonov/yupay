"""Which unique constraint a failed insert broke.

Every catch of ``IntegrityError`` in this module names the constraint it means
to translate and re-raises anything else: a blanket catch once turned an
unrelated failure into a misleading 409.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.exc import IntegrityError


def violated_constraint(exc: IntegrityError, known: Iterable[str]) -> str | None:
    """The constraint ``exc`` reports, or ``None`` when it is none of ``known``.

    asyncpg exposes ``constraint_name`` on the driver error (reached through
    SQLAlchemy's adapter as ``__cause__``); the message text is the fallback.

    Args:
        exc: The error raised by a flush.
        known: The constraint names the caller handles.

    Returns:
        The matching name from ``known``, or ``None``.
    """
    names = tuple(known)
    orig = exc.orig
    cause = getattr(orig, "__cause__", None)
    name = getattr(cause, "constraint_name", None) or getattr(orig, "constraint_name", None)
    if name:
        return str(name) if str(name) in names else None
    text = str(exc)
    return next((n for n in names if n in text), None)


__all__ = ["violated_constraint"]
