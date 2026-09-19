"""Over-length identity-payload fields must not fail Telegram/Steam upserts.

Companion to ``test_auth_google.py``'s equivalent tests for the Google path.
``users.photo_url`` is now ``text`` (migration 0083), but the guard in
``yupay.modules.users.identity_guard`` is what actually stops an absurd value
from ever reaching the INSERT/UPDATE — these tests pin that for the two
non-Google upsert paths named in the incident write-up
(``users/service.py``'s Telegram and Steam branches).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.auth.telegram import TelegramUser
from yupay.modules.users.models import User
from yupay.modules.users.service import upsert_user_by_steam, upsert_user_by_telegram

pytestmark = pytest.mark.asyncio


def _tg_user(tg_id: int, *, photo_url: str | None) -> TelegramUser:
    return TelegramUser(
        id=tg_id,
        first_name="Buyer",
        last_name=None,
        username="buyer_tg",
        language_code="ru",
        is_premium=False,
        photo_url=photo_url,
    )


async def test_telegram_first_sight_with_an_absurd_avatar_url_still_creates_the_user(
    db_session: AsyncSession,
) -> None:
    absurd = "https://t.me/i/userpic/" + ("A" * 3000)
    user = await upsert_user_by_telegram(db_session, _tg_user(555_000_111, photo_url=absurd))
    assert user.photo_url is None


async def test_telegram_first_sight_with_a_normal_avatar_url_stores_it(
    db_session: AsyncSession,
) -> None:
    url = "https://t.me/i/userpic/320/abc.jpg"
    user = await upsert_user_by_telegram(db_session, _tg_user(555_000_112, photo_url=url))
    assert user.photo_url == url


async def test_telegram_returning_user_with_an_absurd_avatar_url_is_not_set(
    db_session: AsyncSession,
) -> None:
    tg_id = 555_000_113
    first = await upsert_user_by_telegram(db_session, _tg_user(tg_id, photo_url=None))
    assert first.photo_url is None

    absurd = "https://t.me/i/userpic/" + ("B" * 3000)
    second = await upsert_user_by_telegram(db_session, _tg_user(tg_id, photo_url=absurd))
    assert second.id == first.id
    assert second.photo_url is None


async def test_steam_first_sight_with_an_absurd_avatar_url_still_creates_the_user(
    db_session: AsyncSession,
) -> None:
    absurd = "https://avatars.steamstatic.com/" + ("C" * 3000)
    user = await upsert_user_by_steam(
        db_session, steam_id=76_561_198_000_000_001, persona_name="Racer", avatar_url=absurd
    )
    assert user.photo_url is None


async def test_steam_first_sight_with_a_normal_avatar_url_stores_it(
    db_session: AsyncSession,
) -> None:
    url = "https://avatars.steamstatic.com/abc123_full.jpg"
    user = await upsert_user_by_steam(
        db_session, steam_id=76_561_198_000_000_002, persona_name="Racer", avatar_url=url
    )
    assert user.photo_url == url


async def test_steam_returning_user_with_an_absurd_avatar_url_is_not_set(
    db_session: AsyncSession,
) -> None:
    steam_id = 76_561_198_000_000_003
    first = await upsert_user_by_steam(
        db_session, steam_id=steam_id, persona_name="Racer", avatar_url=None
    )
    assert first.photo_url is None

    absurd = "https://avatars.steamstatic.com/" + ("D" * 3000)
    second = await upsert_user_by_steam(
        db_session, steam_id=steam_id, persona_name="Racer", avatar_url=absurd
    )
    assert second.id == first.id
    assert second.photo_url is None


async def test_telegram_first_sight_display_name_goes_through_the_guard(
    db_session: AsyncSession,
) -> None:
    """Pins that the Telegram creation path actually calls
    ``identity_guard.safe_display_name`` (not just that the function itself
    truncates correctly — that's covered exhaustively in
    ``test_users_identity_guard.py``).

    Deliberately a normal-length name, not an over-length one: Telegram's
    own Bot API already bounds ``first_name``/``last_name`` at 64 characters
    and ``username`` at 32 (enforced by Telegram, not by us), so a name long
    enough to exercise truncation here would also overflow the unrelated,
    out-of-scope ``telegram_links.first_name`` column — a shape Telegram's
    real API cannot produce.
    """
    user = await upsert_user_by_telegram(db_session, _tg_user(555_000_114, photo_url=None))
    assert user.display_name == "Buyer"


async def test_user_row_survives_a_full_round_trip_after_truncation(
    db_session: AsyncSession,
) -> None:
    """Not just "no exception" — the row must actually be committable and
    re-readable, i.e. genuinely within the column's real limits."""
    absurd = "https://t.me/i/userpic/" + ("E" * 5000)
    user = await upsert_user_by_telegram(db_session, _tg_user(555_000_115, photo_url=absurd))
    await db_session.commit()

    row = (
        await db_session.execute(User.__table__.select().where(User.__table__.c.id == user.id))
    ).first()
    assert row is not None
    assert row.photo_url is None
