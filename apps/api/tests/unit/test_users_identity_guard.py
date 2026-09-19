"""Unit tests for :mod:`yupay.modules.users.identity_guard`.

Sentry: ``POST /api/v1/auth/google`` 500'd with
``asyncpg.exceptions.StringDataRightTruncationError`` on ``INSERT INTO users``
because a Google avatar URL exceeded ``photo_url``'s old ``varchar(1024)``
cap. The column is now ``text`` (migration 0083), but a third party's field
can still send something absurd (megabytes of garbage, a corrupted payload),
so every write site funnels through these two guards instead of trusting the
identity payload directly.
"""

from __future__ import annotations

from yupay.modules.users.identity_guard import safe_avatar_url, safe_display_name


def test_safe_avatar_url_passes_through_a_normal_url() -> None:
    url = "https://lh3.googleusercontent.com/a-/AAA1234"
    assert safe_avatar_url(url) == url


def test_safe_avatar_url_none_stays_none() -> None:
    assert safe_avatar_url(None) is None


def test_safe_avatar_url_blank_becomes_none() -> None:
    assert safe_avatar_url("   ") is None


def test_safe_avatar_url_strips_surrounding_whitespace() -> None:
    assert safe_avatar_url("  https://example.test/a.png  ") == "https://example.test/a.png"


def test_safe_avatar_url_drops_an_absurdly_long_url() -> None:
    """The production incident: a real Google avatar URL past 1024 chars.

    A truncated URL is not a smaller picture — it is a broken link — so the
    guard drops it entirely rather than truncating it into garbage; the
    caller ends up with "no avatar", the same as if none had been supplied.
    """
    absurd = "https://lh3.googleusercontent.com/" + ("a" * 3000)
    assert safe_avatar_url(absurd) is None


def test_safe_avatar_url_accepts_up_to_the_configured_limit() -> None:
    from yupay.modules.users.identity_guard import MAX_AVATAR_URL_LENGTH

    just_fits = "https://example.test/" + (
        "a" * (MAX_AVATAR_URL_LENGTH - len("https://example.test/"))
    )
    assert len(just_fits) == MAX_AVATAR_URL_LENGTH
    assert safe_avatar_url(just_fits) == just_fits

    one_over = just_fits + "a"
    assert safe_avatar_url(one_over) is None


def test_safe_display_name_passes_through_a_normal_name() -> None:
    assert safe_display_name("Buyer Person") == "Buyer Person"


def test_safe_display_name_none_stays_none() -> None:
    assert safe_display_name(None) is None


def test_safe_display_name_blank_becomes_none() -> None:
    assert safe_display_name("   ") is None


def test_safe_display_name_truncates_an_over_length_name() -> None:
    """Unlike a URL, a shortened name is still a usable name, so this guard
    truncates instead of dropping — losing the tail of an unusually long
    name is a smaller harm than losing the name (and the registration)."""
    from yupay.modules.users.identity_guard import MAX_DISPLAY_NAME_LENGTH

    long_name = "A" * (MAX_DISPLAY_NAME_LENGTH + 50)
    result = safe_display_name(long_name)
    assert result is not None
    assert len(result) == MAX_DISPLAY_NAME_LENGTH
    assert result == "A" * MAX_DISPLAY_NAME_LENGTH
