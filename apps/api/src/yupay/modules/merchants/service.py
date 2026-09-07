"""The merchant account itself — create it, load it, freeze it.

The row a reseller *is*. Everything that hangs off it lives beside this file
rather than in it, because "merchant" turned out to be three responsibilities
wearing one name and 487 lines (AGENTS.md §6 puts the soft limit at 400):

| Concern                         | Where            |
| ------------------------------- | ---------------- |
| The account (here)              | ``service.py``   |
| Its machine credentials         | ``credentials.py`` |
| Its USD deposit and the ledger  | ``deposit.py``   |

Both of those import :func:`get_merchant` from here and nothing else, so the
dependency runs one way and this file has no idea either of them exists.

Freezing a merchant (:func:`set_status`) blocks ORDERS — the ``merchant_auth``
dependency refuses a frozen merchant with 403 ``merchant_frozen`` — never
money in: support can always credit a frozen merchant's deposit, e.g. to
settle a dispute while the account is under review. That asymmetry is
deliberate and is why ``deposit.credit_deposit`` does not consult ``status``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.modules.merchants.models import Merchant

_STATUSES = ("active", "frozen")


async def get_merchant(db: AsyncSession, merchant_id: str) -> Merchant:
    """Load a merchant row or raise.

    Public rather than private because ``credentials`` and ``deposit`` both
    need it: every operation on a merchant's keys or money starts by proving
    the merchant exists, and a typo'd id must be a 404 rather than an empty
    list or a zero balance. Not re-exported from ``api`` — it is an
    intra-module helper, not part of the module's surface.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The ``merchants.id`` to load.

    Returns:
        The merchant row.

    Raises:
        NotFoundError: If no merchant with that id exists.
    """
    merchant = (
        await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    ).scalar_one_or_none()
    if merchant is None:
        raise NotFoundError("merchant not found")
    return merchant


async def create_merchant(db: AsyncSession, *, title: str) -> Merchant:
    """Create a reseller account.

    Args:
        db: Session. The caller owns the transaction.
        title: Human-readable merchant name, non-blank.

    Returns:
        The new merchant, with server defaults (``status``, ``created_at``)
        populated.

    Raises:
        ValidationError: If ``title`` is blank.
    """
    cleaned = title.strip()
    if not cleaned:
        raise ValidationError("merchant title must not be blank")
    merchant = Merchant(id=new_id(), title=cleaned)
    db.add(merchant)
    await db.flush()
    # Pick up the server-side defaults so callers see status='active' without
    # a round-trip of their own.
    await db.refresh(merchant)
    return merchant


async def set_status(db: AsyncSession, *, merchant_id: str, status: str) -> Merchant:
    """Set a merchant's status to ``active`` or ``frozen``.

    Freezing blocks new orders, not deposits — see the module docstring.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose status to change.
        status: One of ``active`` / ``frozen``.

    Returns:
        The updated merchant row.

    Raises:
        ValidationError: If ``status`` is not a known value.
        NotFoundError: If no merchant with that id exists.
    """
    if status not in _STATUSES:
        raise ValidationError(
            "merchant status must be 'active' or 'frozen'", extra={"status": status}
        )
    merchant = await get_merchant(db, merchant_id)
    merchant.status = status
    await db.flush()
    return merchant


__all__ = [
    "create_merchant",
    "get_merchant",
    "set_status",
]
