"""A buyer deleting their own account (the stores require it in the app).

Deletion is a tombstone, not an erasure (owner, 2026-10-22): ``users.deleted_at`` is set and
nothing else is removed. Orders, payments and the wallet ledger are financial records and stay
as they were; the remaining balance stays on the ledger, out of the buyer's reach. What the
tombstone does:

* every read of the account — ``current_user``, refresh, password login, Google by email —
  already filters ``deleted_at IS NULL``, so the account cannot be entered again;
* every open session is revoked and its access tokens blocklisted at once;
* the account's push devices are disabled;
* the email is free again (``uq_users_email_alive`` is partial), and a Telegram or Steam
  identity signing in again gets a fresh account that takes over the link
  (``users.service.upsert_user_by_*``).

An operator account (any role) cannot delete itself here: losing the admin by a tap in the
shop app is not a thing to make possible.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.errors import ConflictError
from yupay.core.logging import get_logger
from yupay.modules.auth.service import _revoke_all_for_user
from yupay.modules.users.models import User

log = get_logger("yupay.auth.account_deletion")


async def delete_account(db: AsyncSession, user: User, *, settings: Settings | None = None) -> None:
    """Tombstone the signed-in buyer's account and close every way back into it.

    Args:
        db: Session; the caller commits.
        user: The account, from ``current_user`` (so it is alive and not banned).
        settings: Optional override.

    Raises:
        ConflictError: The account carries a role (admin, operator).
    """
    if user.roles:
        raise ConflictError(
            "an operator account cannot be deleted from the app",
            extra={"code": "has_roles"},
        )
    user.deleted_at = now()
    user.updated_at = user.deleted_at
    await db.flush()
    await _revoke_all_for_user(db, user.id, settings=settings or get_settings())
    # Lazy: push's routes depend on auth, so a top-level import would be a cycle.
    from yupay.modules.push.api import disable_all

    devices = await disable_all(db, user_id=user.id, reason="account_deleted")
    log.info("auth.account_deleted", user_id=user.id, push_devices=devices)
