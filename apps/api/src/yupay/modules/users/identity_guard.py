"""Length guards for identity-payload fields copied onto a :class:`User`.

``photo_url`` and ``display_name`` are populated from whatever a third-party
identity provider (Google, Telegram, Steam) hands back, un-validated by that
provider's own contract. Sentry: ``POST /api/v1/auth/google`` 500'd with
``asyncpg.exceptions.StringDataRightTruncationError`` because a real Google
avatar URL exceeded the (then) ``photo_url`` column's ``varchar(1024)`` cap —
a rare shape (893 users had one on record, longest 100 chars) that still
failed closed at the worst possible moment: a first registration.

Migration 0083 widened ``users.photo_url`` to ``text`` (effectively
unbounded — see its docstring for why that is a metadata-only ALTER, no
table rewrite), which closes the specific incident. This module is the
second half: a length a real browser would never render should never even
reach an INSERT, on this column or the next one a provider surprises us
with. :func:`safe_avatar_url` and :func:`safe_display_name` are the single
place every write site funnels through — see ``users.service`` (Telegram,
Steam) and ``auth.service.google_login`` (Google) — so there is one limit to
tune, not six copies of it.
"""

from __future__ import annotations

from sqlalchemy import String

from yupay.modules.users.models import User

#: Generous headroom over anything a real avatar URL has ever measured here
#: (the longest of 893 on file is 100 chars; the incident URL was "past
#: 1024"), while still refusing something pathological (a multi-KB payload,
#: a corrupted value) long before it reaches Postgres. Independent of the
#: column width — the column is `text` precisely so a value this function
#: accepts can never again fail the INSERT/UPDATE on its own.
MAX_AVATAR_URL_LENGTH = 2048

#: ``users.display_name``'s own column width (``String(255)``, unchanged by
#: migration 0083 — see its docstring for why only ``photo_url`` needed
#: widening), read off the model rather than hand-copied: a narrower column
#: (or a wider one) then changes this guard automatically instead of leaving
#: it silently out of sync — over-permissive if the column ever shrinks
#: without this being touched too. A name has no "broken" state the way a
#: truncated URL does, so this guard truncates instead of dropping.
_display_name_type = User.__table__.c.display_name.type
assert isinstance(_display_name_type, String), "users.display_name must stay a String column"
assert _display_name_type.length is not None, "users.display_name must stay length-bounded"
MAX_DISPLAY_NAME_LENGTH: int = _display_name_type.length


def safe_avatar_url(url: str | None) -> str | None:
    """Return ``url`` unchanged, or ``None`` if absent/blank/absurdly long.

    A truncated URL is not a smaller picture — it is a broken link — so
    "too long" is treated exactly like "not supplied": no avatar, never a
    corrupted one.

    Args:
        url: The candidate avatar URL from an identity provider payload.

    Returns:
        The stripped URL, or ``None`` when there is nothing safe to store.
    """
    if url is None:
        return None
    stripped = url.strip()
    if not stripped or len(stripped) > MAX_AVATAR_URL_LENGTH:
        return None
    return stripped


def safe_display_name(name: str | None) -> str | None:
    """Return ``name`` unchanged, or truncated to fit, or ``None`` if blank.

    Unlike a URL, a shortened name is still a usable name — dropping it
    would replace a real (if unusually long) name with nothing, a worse
    outcome for a field that is only ever shown back to its own owner.

    Args:
        name: The candidate display name from an identity provider payload.

    Returns:
        The stripped (and possibly truncated) name, or ``None`` when blank.
    """
    if name is None:
        return None
    stripped = name.strip()
    if not stripped:
        return None
    return stripped[:MAX_DISPLAY_NAME_LENGTH]


__all__ = [
    "MAX_AVATAR_URL_LENGTH",
    "MAX_DISPLAY_NAME_LENGTH",
    "safe_avatar_url",
    "safe_display_name",
]
