"""User upsert / lookup service.

All cross-module callers should import from :mod:`yupay.modules.users.api`, never from
here directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yupay.core.clock import now
from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.ids import new_id
from yupay.modules.auth.telegram import TelegramUser
from yupay.modules.users.identity_guard import safe_avatar_url, safe_display_name
from yupay.modules.users.models import SteamLink, TelegramLink, User
from yupay.modules.users.schemas import UserAdminSort
from yupay.modules.wallet.balances import (
    balances_for_users,
    user_wallet_totals,
    user_wallet_usd_sort_subquery,
)


async def get_user_by_id(session: AsyncSession, user_id: str) -> User | None:
    """Return the user row or ``None`` if not found / soft-deleted."""
    stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_user_by_telegram_id(session: AsyncSession, tg_user_id: int) -> User | None:
    """Look up the user joined to a Telegram identity, if any."""
    stmt = (
        select(User)
        .join(TelegramLink, TelegramLink.user_id == User.id)
        .where(TelegramLink.tg_user_id == tg_user_id, User.deleted_at.is_(None))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _is_unique_violation(exc: IntegrityError) -> bool:
    """Whether ``exc`` is a UNIQUE-constraint violation (Postgres SQLSTATE
    ``23505``), not some other integrity failure.

    The recovery below re-reads and returns the concurrent winner's row on
    ``IntegrityError`` — correct only for the specific unique-index race
    ``upsert_user_by_telegram``/``upsert_user_by_steam`` exist to handle.
    Catching bare ``IntegrityError`` would also absorb a NOT NULL or FK
    violation from a real bug, as long as the identity row happened to
    already exist for an unrelated reason (the re-read's ``if … is None:
    raise`` only catches the case where it does *not*). Checking the
    SQLSTATE narrows the catch to the one failure the recovery is designed
    for, and re-raises everything else.
    """
    return getattr(exc.orig, "sqlstate", None) == "23505"


def _normalised_language_code(code: str | None) -> str | None:
    """Fit a raw IETF language tag into ``telegram_links.language_code``'s
    ``varchar(8)``, the same primary-subtag-only truncation ``locale`` above
    already applies before it reaches ``users.locale`` (also ``varchar(8)``).

    Telegram hands back whatever the client reports, unvalidated — a tag
    like ``zh-Hant-TW`` is 10 characters and would fail the INSERT/UPDATE on
    this column in the same flush that writes the (already-guarded)
    ``locale``. Returns ``None`` for absent/blank input; the column is
    nullable, unlike ``users.locale``, so there is no default to fall back
    to here.
    """
    if not code:
        return None
    return code.split("-")[0][:8] or None


async def upsert_user_by_telegram(
    session: AsyncSession,
    tg_user: TelegramUser,
    *,
    locale_hint: str | None = None,
) -> User:
    """Find-or-create a user from a verified Telegram identity.

    On first sight we create both the ``users`` row and the ``telegram_links`` row.
    On subsequent visits we touch ``last_seen_at`` and refresh mutable Telegram fields.
    The ``locale_hint`` is only applied at creation time — we don't override an existing
    user's locale choice.

    First-sight creation is find-or-create over a plain SELECT-then-INSERT, so
    two concurrent first logins for the same brand-new Telegram id race it:
    both see "not found" and both try to insert. Sentry, production,
    2026-09-18: the loser hit ``asyncpg.UniqueViolationError`` on
    ``uq_telegram_links_tg_user_id`` and 500'd — someone opening the app for
    the first time got a 500 for it. The INSERT now runs inside a
    ``db.begin_nested()`` SAVEPOINT; on ``IntegrityError`` the loser re-reads
    the winner's already-committed row and falls through into the same
    "existing user" branch below, exactly as if it had found the row on the
    first SELECT.
    """
    existing = await get_user_by_telegram_id(session, tg_user.id)
    if existing is None:
        locale = (locale_hint or tg_user.language_code or "ru").split("-")[0][:8] or "ru"
        user = User(
            id=new_id(),
            email=None,
            locale=locale,
            display_name=safe_display_name(tg_user.first_name or tg_user.username),
            photo_url=safe_avatar_url(tg_user.photo_url),
        )
        new_link = TelegramLink(
            id=new_id(),
            user_id=user.id,
            tg_user_id=tg_user.id,
            tg_username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            language_code=_normalised_language_code(tg_user.language_code),
            is_premium=tg_user.is_premium,
        )
        try:
            # Rows added *inside* the SAVEPOINT, not before it opens: added
            # earlier, a UNIQUE(tg_user_id) failure would leave the doomed
            # rows sitting in session.new and poison the outer transaction
            # (begin_nested() autoflushes already-pending state first — see
            # affiliate.partners / fulfillment's own begin_nested() notes).
            async with session.begin_nested():
                session.add(user)
                session.add(new_link)
                await session.flush()
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            existing = await get_user_by_telegram_id(session, tg_user.id)
            if existing is None:
                raise
        else:
            return user

    link = existing.telegram_link
    if link is not None:
        link.tg_username = tg_user.username
        link.first_name = tg_user.first_name
        link.last_name = tg_user.last_name
        link.language_code = _normalised_language_code(tg_user.language_code)
        link.is_premium = tg_user.is_premium
        link.last_seen_at = now()
    photo_url = safe_avatar_url(tg_user.photo_url)
    if photo_url and not existing.photo_url:
        existing.photo_url = photo_url
    existing.updated_at = now()
    await session.flush()
    return existing


async def _get_steam_link(session: AsyncSession, steam_id: int) -> SteamLink | None:
    """Look up the :class:`SteamLink` row (with its joined user) by steamid64."""
    return (
        await session.execute(select(SteamLink).where(SteamLink.steam_id == steam_id))
    ).scalar_one_or_none()


async def upsert_user_by_steam(
    session: AsyncSession,
    *,
    steam_id: int,
    persona_name: str | None = None,
    avatar_url: str | None = None,
) -> User:
    """Find-or-create a user from a verified Steam identity.

    Mirrors :func:`upsert_user_by_telegram`, race handling included: first
    sight creates the ``users`` row and the ``steam_links`` row; later visits
    touch ``last_seen_at`` and refresh the mutable Steam fields. Two
    concurrent first logins for the same steamid64 both see "not found" and
    both try to insert; the loser now recovers from the ``IntegrityError`` on
    ``steam_links.steam_id`` by re-reading the winner's row and falling
    through into the "existing" branch, instead of 500ing — see
    :func:`upsert_user_by_telegram`'s docstring for the shape.

    ``avatar_url`` is guarded once and reused for both ``steam_links
    .avatar_url`` and ``users.photo_url``: they are written in the same
    flush from the same value, so guarding only one still leaves the other
    free to fail the INSERT/UPDATE on an absurd value — the exact failure
    mode this guard exists to prevent, just on a different column.
    Migration 0083 widens both columns to ``text`` for the same reason. An
    earlier draft widened only ``users.photo_url``, on the argument that
    Steam's avatar URLs are short fixed-format CDN links — which is true, and
    is exactly what was true of Google's avatar URLs until one of them ran
    past 1024 characters and cost somebody their registration. Leaving the
    sibling at ``varchar(1024)`` would have kept a live gap between the
    guard's ceiling and the column's, reachable by a value the guard accepts.

    ``persona_name`` gets the identical treatment for the identical reason:
    ``safe_display_name(persona_name)`` goes onto ``users.display_name``,
    but the raw ``persona_name`` — straight from the Steam Web API, the same
    class of unvalidated third-party field ``avatar_url`` is — used to go
    onto ``steam_links.persona_name`` unguarded, in the same flush. A
    personaname over 255 characters would truncate harmlessly into
    ``display_name`` and then fail the INSERT/UPDATE on its sibling column.
    Guarded once here and reused at both write sites below, same shape as
    ``avatar``.
    """
    avatar = safe_avatar_url(avatar_url)
    name = safe_display_name(persona_name)
    link = await _get_steam_link(session, steam_id)
    if link is None:
        user = User(
            id=new_id(),
            email=None,
            locale="ru",
            display_name=name,
            photo_url=avatar,
        )
        new_link = SteamLink(
            id=new_id(),
            user_id=user.id,
            steam_id=steam_id,
            persona_name=name,
            avatar_url=avatar,
        )
        try:
            # See upsert_user_by_telegram: rows added inside the SAVEPOINT,
            # not before it opens.
            async with session.begin_nested():
                session.add(user)
                session.add(new_link)
                await session.flush()
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            link = await _get_steam_link(session, steam_id)
            if link is None:
                raise
        else:
            return user

    link.persona_name = name or link.persona_name
    link.avatar_url = avatar or link.avatar_url
    link.last_seen_at = now()
    user = link.user
    if avatar and not user.photo_url:
        user.photo_url = avatar
    user.updated_at = now()
    await session.flush()
    return user


@dataclass(frozen=True)
class AdminUserListPage:
    """One page of the admin user directory, plus global wallet liability."""

    users: list[User]
    total: int
    wallets: dict[str, list[tuple[str, Decimal]]]
    totals: list[tuple[str, Decimal]]


async def list_users_admin(
    session: AsyncSession,
    *,
    search: str | None = None,
    sort: UserAdminSort = "created_desc",
    limit: int = 50,
    offset: int = 0,
) -> AdminUserListPage:
    """Admin listing with optional substring search and server-side sort.

    Search matches display_name / email / Telegram username/id / Steam
    persona/id. ``wallet_*`` sorts convert non-USD ``user_wallet`` balances
    through the latest ``fx_rates`` row so mixed-currency pages have one
    order; the cell still shows native amounts.
    """
    base = select(User).options(selectinload(User.telegram_link), selectinload(User.steam_link))
    count_stmt = select(func.count()).select_from(User)
    if search and search.strip():
        q = f"%{search.strip()}%"
        as_int = None
        if search.strip().isdigit():
            try:
                as_int = int(search.strip())
            except ValueError:
                as_int = None
        join_clauses = [
            User.display_name.ilike(q),
            User.email.ilike(q),
        ]
        # Telegram-side filters need a join. We do an outer join so a user
        # without a TG link can still match by display_name/email above.
        base = base.outerjoin(TelegramLink, TelegramLink.user_id == User.id).outerjoin(
            SteamLink, SteamLink.user_id == User.id
        )
        count_stmt = count_stmt.outerjoin(TelegramLink, TelegramLink.user_id == User.id).outerjoin(
            SteamLink, SteamLink.user_id == User.id
        )
        join_clauses.append(TelegramLink.tg_username.ilike(q))
        join_clauses.append(SteamLink.persona_name.ilike(q))
        if as_int is not None:
            join_clauses.append(TelegramLink.tg_user_id == as_int)  # type: ignore[arg-type]
            join_clauses.append(SteamLink.steam_id == as_int)  # type: ignore[arg-type]
        base = base.where(or_(*join_clauses))
        count_stmt = count_stmt.where(or_(*join_clauses))

    base = _apply_user_list_sort(base, sort)
    items = list((await session.execute(base.limit(limit).offset(offset))).unique().scalars().all())
    total = int((await session.execute(count_stmt)).scalar_one() or 0)
    wallets = await balances_for_users(session, [u.id for u in items])
    totals = await user_wallet_totals(session)
    return AdminUserListPage(users=items, total=total, wallets=wallets, totals=totals)


def _apply_user_list_sort(base: Select[tuple[User]], sort: UserAdminSort) -> Select[tuple[User]]:
    """Attach ORDER BY. ``created_at`` alone is not stable under OFFSET
    (every row a single request writes shares one transaction timestamp);
    ``id`` is the tiebreak, same shape as migration 0055 on orders."""
    if sort in ("wallet_desc", "wallet_asc"):
        wallet = user_wallet_usd_sort_subquery()
        joined = base.outerjoin(wallet, wallet.c.owner_id == cast(User.id, String))
        usd_eq = func.coalesce(wallet.c.usd_eq, 0)
        order_expr = usd_eq.desc() if sort == "wallet_desc" else usd_eq.asc()
        return joined.order_by(order_expr, User.created_at.desc(), User.id.desc())
    if sort == "created_asc":
        return base.order_by(User.created_at.asc(), User.id.asc())
    if sort == "name_asc":
        return base.order_by(
            func.lower(User.display_name).asc().nulls_last(),
            User.created_at.desc(),
            User.id.desc(),
        )
    if sort == "name_desc":
        return base.order_by(
            func.lower(User.display_name).desc().nulls_last(),
            User.created_at.desc(),
            User.id.desc(),
        )
    return base.order_by(User.created_at.desc(), User.id.desc())


async def get_user_admin(session: AsyncSession, user_id: str) -> User:
    """Load a user with the Telegram link eager-loaded; 404 if missing."""
    stmt = (
        select(User)
        .options(selectinload(User.telegram_link), selectinload(User.steam_link))
        .where(User.id == user_id)
    )
    row = (await session.execute(stmt)).unique().scalar_one_or_none()
    if row is None:
        raise NotFoundError("user not found")
    return row


async def ban_user(
    session: AsyncSession, user_id: str, *, by_admin_id: str, reason: str | None = None
) -> User:
    """Suspend an account. Idempotent — re-banning refreshes reason and actor.

    Two guards, both about not letting the tool turn on its operators: an admin
    cannot ban themselves (the obvious way to lose the only admin account), and
    cannot ban another admin (a fight between two admins should be settled in
    the database by a human, not by whoever clicks first).

    Sessions are left alone deliberately. ``auth.current_user`` re-reads the ban
    on every authenticated request, so access dies at once anyway; revoking
    sessions here would add a second mechanism to keep in sync for no gain.
    """
    user = await get_user_admin(session, user_id)
    if user.id == by_admin_id:
        raise ValidationError("an admin cannot ban themselves")
    if "admin" in (user.roles or []):
        raise ValidationError(
            "cannot ban an admin — remove the admin role first",
            extra={"user_id": user_id},
        )
    user.banned_at = now()
    user.ban_reason = (reason or "").strip()[:500] or None
    user.banned_by = by_admin_id
    user.updated_at = now()
    await session.flush()
    return user


async def unban_user(session: AsyncSession, user_id: str) -> User:
    """Lift a suspension. Idempotent — unbanning an active account is a no-op.

    Clears the reason and actor along with the timestamp: keeping them would
    leave a record that reads like an active ban to anyone scanning the row.
    """
    user = await get_user_admin(session, user_id)
    user.banned_at = None
    user.ban_reason = None
    user.banned_by = None
    user.updated_at = now()
    await session.flush()
    return user


async def is_email_banned(session: AsyncSession, email: str) -> bool:
    """Whether ``email`` belongs to a suspended account.

    Guest checkout creates no user row, so a ban would otherwise be lifted by
    simply not logging in. This closes that door for the banned identity — not
    for the person, who can use another address. See ADR-0045: a ban stops an
    account, and pretending otherwise is how a control becomes theatre.
    """
    stmt = select(User.id).where(
        User.email == email.strip().lower(),
        User.banned_at.is_not(None),
        User.deleted_at.is_(None),
    )
    return (await session.execute(stmt)).first() is not None


# Roles we accept on a user record. Anything else is rejected at the route layer.
_ALLOWED_ROLES = frozenset({"admin"})


async def set_user_roles(session: AsyncSession, user_id: str, *, roles: list[str]) -> User:
    """Replace the user's roles list. Unknown roles raise NotFoundError-friendly
    error via core.errors. Empty list means "demote to plain user"."""
    user = await get_user_admin(session, user_id)
    cleaned: list[str] = []
    seen: set[str] = set()
    for r in roles:
        r2 = r.strip().lower()
        if not r2 or r2 in seen:
            continue
        if r2 not in _ALLOWED_ROLES:
            from yupay.core.errors import ValidationError

            raise ValidationError(f"unknown role: {r2}", allowed=sorted(_ALLOWED_ROLES))
        seen.add(r2)
        cleaned.append(r2)
    user.roles = cleaned
    user.updated_at = now()
    await session.flush()
    return user


# Mirror of the Pydantic Literal in ``schemas.UpdateMeIn``. Defining it here
# too keeps the service layer self-contained for cross-module callers that
# import ``users.api`` without pulling Pydantic in.
_ALLOWED_DISPLAY_CURRENCIES = frozenset({"USD", "UZS", "RUB", "USDT"})
# Locales the storefront has UI translations for. Mirror of ``LocaleLiteral``
# in ``schemas`` and ``LOCALES`` in ``packages/i18n``.
_ALLOWED_LOCALES = frozenset({"ru", "en", "uz"})


async def update_me(
    session: AsyncSession,
    user_id: str,
    *,
    display_currency: str | None = None,
    locale: str | None = None,
    delivery_email: str | None = None,
) -> User:
    """Patch the authenticated user's preferences.

    Only fields whose value is not ``None`` are touched, so callers can send
    partial bodies. Unknown currencies are rejected as a 400 — they would
    otherwise break the storefront's FX lookup and silently degrade prices.
    """
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise NotFoundError("user not found")
    if display_currency is not None:
        currency = display_currency.strip().upper()
        if currency not in _ALLOWED_DISPLAY_CURRENCIES:
            from yupay.core.errors import ValidationError

            raise ValidationError(
                f"unsupported display currency: {currency!r}",
                allowed=sorted(_ALLOWED_DISPLAY_CURRENCIES),
            )
        user.display_currency = currency
    if locale is not None:
        cleaned = locale.strip().lower().split("-")[0][:8]
        if cleaned not in _ALLOWED_LOCALES:
            from yupay.core.errors import ValidationError

            raise ValidationError(
                f"unsupported locale: {cleaned!r}",
                allowed=sorted(_ALLOWED_LOCALES),
            )
        user.locale = cleaned
    if delivery_email is not None:
        # Empty string is the documented "clear it" signal — the only way back
        # to "use my account address" once one is set. Never touches
        # ``user.email``: that is the login identity, unique and resolved by
        # the auth service, and a settings screen must not be able to move it.
        user.delivery_email = delivery_email.strip().lower() or None
    user.updated_at = now()
    await session.flush()
    return user


__all__ = [
    "AdminUserListPage",
    "get_user_admin",
    "get_user_by_id",
    "get_user_by_telegram_id",
    "list_users_admin",
    "set_user_roles",
    "update_me",
    "upsert_user_by_steam",
    "upsert_user_by_telegram",
]
