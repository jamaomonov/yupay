"""Per-bucket thresholds for the IP guard.

Every bucket used to share one ``AUTH_IP_GUARD_MAX``, which is written for
brute-force endpoints: ten tries a minute is plenty for a login and far too
few for the storefront's player check, where a mobile carrier puts many
customers behind one address and they spend that budget collectively.

The guard is Redis-backed, so these tests call ``bucket_limit`` -- the pure
resolution step -- rather than driving Redis, and an integration test covers
the wiring end to end.
"""

from __future__ import annotations

import pytest
from yupay.core.config import get_settings
from yupay.modules.auth.ip_guard import bucket_limit


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_unlisted_bucket_keeps_the_brute_force_default(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_IP_GUARD_MAX", "10")
    assert bucket_limit(get_settings(), "login") == 10


def test_player_check_gets_its_own_looser_budget(monkeypatch) -> None:
    """The whole point: raising it must not raise `login` with it."""
    monkeypatch.setenv("AUTH_IP_GUARD_MAX", "10")
    s = get_settings()
    assert bucket_limit(s, "check_player") > bucket_limit(s, "login")


def test_an_operator_can_retune_one_bucket(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_IP_GUARD_MAX", "10")
    monkeypatch.setenv("AUTH_IP_GUARD_BUCKET_MAX", '{"check_player": 45}')
    s = get_settings()
    assert bucket_limit(s, "check_player") == 45
    assert bucket_limit(s, "login") == 10


def test_a_bucket_can_be_tightened_below_the_default(monkeypatch) -> None:
    """Overrides are not "raise only" -- an abused bucket must be squeezable."""
    monkeypatch.setenv("AUTH_IP_GUARD_MAX", "10")
    monkeypatch.setenv("AUTH_IP_GUARD_BUCKET_MAX", '{"code-access": 3}')
    assert bucket_limit(get_settings(), "code-access") == 3


def test_a_malformed_override_never_disables_the_guard(monkeypatch) -> None:
    """A bad value in the env must degrade to the default, not to "no limit".

    Pydantic rejects unparseable JSON for a dict field outright, so the failure
    mode to guard is a *parseable* value carrying nonsense: 0 or a negative
    would read as "allow nothing" or, past the `count > limit` comparison,
    "allow everything".
    """
    monkeypatch.setenv("AUTH_IP_GUARD_MAX", "10")
    monkeypatch.setenv("AUTH_IP_GUARD_BUCKET_MAX", '{"login": 0, "register": -5}')
    s = get_settings()
    assert bucket_limit(s, "login") == 10
    assert bucket_limit(s, "register") == 10
