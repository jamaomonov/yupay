"""Grant or revoke the ``admin`` role on a user.

Used to bootstrap the first admin: the founder logs in via Telegram once (creating
the ``users`` row), then runs this script with the resulting telegram id.

Usage:
    python -m yupay.scripts.grant_admin --tg-id 123456789
    python -m yupay.scripts.grant_admin --user-id 019e...-... --role admin
    python -m yupay.scripts.grant_admin --tg-id 123456789 --revoke
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from yupay.core.db import get_session_factory
from yupay.modules.users.models import TelegramLink, User


async def _grant(*, tg_id: int | None, user_id: str | None, role: str, revoke: bool) -> int:
    factory = get_session_factory()
    async with factory() as session:
        if tg_id is not None:
            user = (
                await session.execute(
                    select(User)
                    .join(TelegramLink, TelegramLink.user_id == User.id)
                    .where(TelegramLink.tg_user_id == tg_id, User.deleted_at.is_(None))
                )
            ).scalar_one_or_none()
        else:
            user = (
                await session.execute(
                    select(User).where(User.id == user_id, User.deleted_at.is_(None))
                )
            ).scalar_one_or_none()

        if user is None:
            print(
                f"[grant_admin] no user matched (tg_id={tg_id}, user_id={user_id}).",
                file=sys.stderr,
            )
            return 2

        roles = set(user.roles or [])
        if revoke:
            roles.discard(role)
            action = "revoked"
        else:
            roles.add(role)
            action = "granted"

        user.roles = sorted(roles)
        await session.commit()

        print(
            f"[grant_admin] {action} '{role}' for user={user.id} "
            f"(roles={user.roles})"
        )
        return 0


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tg-id", type=int, help="Telegram user id")
    group.add_argument("--user-id", type=str, help="YuPay user id (UUID)")
    parser.add_argument(
        "--role",
        type=str,
        default="admin",
        help="Role to grant/revoke (default: admin)",
    )
    parser.add_argument(
        "--revoke", action="store_true", help="Revoke the role instead of granting"
    )
    args = parser.parse_args()

    return asyncio.run(
        _grant(
            tg_id=args.tg_id,
            user_id=args.user_id,
            role=args.role,
            revoke=args.revoke,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
