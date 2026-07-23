"""Tests for the Click Shop API sign_string build + verify (``signature.py``).

Click authenticates every Prepare/Complete webhook with an MD5 ``sign_string``
keyed on a per-service ``SECRET_KEY``. The cross-checks below hand-build the
same concatenation from the raw field values independently of the module
under test, so a passing test is real evidence the formula matches Click's
docs (see ``docs/superpowers/specs/2026-07-23-click-shop-api-design.md`` §6),
not a self-referential assertion.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator

import pytest
from yupay.core import config as cfg
from yupay.modules.click import signature


@pytest.fixture
def _clear_settings_cache() -> Iterator[None]:
    """Clear the cached ``Settings`` before and after each test.

    ``get_settings`` is process-lifetime cached via ``lru_cache``. Without
    clearing on both sides, whichever test in the suite calls it first
    freezes the result for every test that follows — including ones outside
    this module. Mirrors the fixture in ``test_uzum_config.py``.
    """
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture
def _click_env(monkeypatch: pytest.MonkeyPatch, _clear_settings_cache: None) -> None:
    """Configure both Click services (web + bot) with distinct secrets."""
    monkeypatch.setenv("CLICK_SERVICE_ID_WEB", "108149")
    monkeypatch.setenv("CLICK_SERVICE_ID_BOT", "108150")
    monkeypatch.setenv("CLICK_SECRET_KEY_WEB", "web-secret-abc")
    monkeypatch.setenv("CLICK_SECRET_KEY_BOT", "bot-secret-xyz")
    cfg.get_settings.cache_clear()


# --- prepare_sign ---


def test_prepare_sign_matches_hand_computed_md5() -> None:
    click_trans_id = "123456789"
    service_id = "108149"
    secret = "sUpEr-SeCrEt"
    merchant_trans_id = "ord_0001"
    amount = "1000.00"
    action = "0"
    sign_time = "2026-07-23 12:00:00"

    expected = hashlib.md5(
        (
            click_trans_id + service_id + secret + merchant_trans_id + amount + action + sign_time
        ).encode()
    ).hexdigest()

    result = signature.prepare_sign(
        click_trans_id=click_trans_id,
        service_id=service_id,
        secret=secret,
        merchant_trans_id=merchant_trans_id,
        amount=amount,
        action=action,
        sign_time=sign_time,
    )

    assert result == expected
    # Pinned literal, computed independently via a standalone `python3 -c`
    # invocation (not this test process) from the exact same raw strings —
    # guards against both this test and the implementation sharing a bug.
    assert result == "2043542acca0f997a40ebff461b9b6a8"


# --- complete_sign ---


def test_complete_sign_matches_hand_computed_md5_with_prepare_id_after_trans_id() -> None:
    click_trans_id = "123456789"
    service_id = "108149"
    secret = "sUpEr-SeCrEt"
    merchant_trans_id = "ord_0001"
    merchant_prepare_id = "42"
    amount = "1000.00"
    action = "1"
    sign_time = "2026-07-23 12:05:00"

    expected = hashlib.md5(
        (
            click_trans_id
            + service_id
            + secret
            + merchant_trans_id
            + merchant_prepare_id
            + amount
            + action
            + sign_time
        ).encode()
    ).hexdigest()

    result = signature.complete_sign(
        click_trans_id=click_trans_id,
        service_id=service_id,
        secret=secret,
        merchant_trans_id=merchant_trans_id,
        merchant_prepare_id=merchant_prepare_id,
        amount=amount,
        action=action,
        sign_time=sign_time,
    )

    assert result == expected


def test_complete_sign_differs_from_prepare_sign_placement_of_prepare_id() -> None:
    """Guards against a slot-order bug: putting ``merchant_prepare_id`` anywhere
    other than immediately after ``merchant_trans_id`` would silently pass a
    same-length test but not Click's actual verification."""
    kwargs = {
        "click_trans_id": "1",
        "service_id": "108149",
        "secret": "s",
        "merchant_trans_id": "ord",
        "amount": "1.00",
        "action": "1",
        "sign_time": "2026-07-23 00:00:00",
    }
    wrong_order = hashlib.md5(
        (
            kwargs["click_trans_id"]
            + kwargs["service_id"]
            + kwargs["secret"]
            + kwargs["merchant_trans_id"]
            + kwargs["amount"]
            + kwargs["action"]
            + kwargs["sign_time"]
            + "99"  # merchant_prepare_id tacked on at the end instead
        ).encode()
    ).hexdigest()

    result = signature.complete_sign(merchant_prepare_id="99", **kwargs)

    assert result != wrong_order


# --- verify ---


def test_verify_true_for_matching_hex_any_case() -> None:
    digest = hashlib.md5(b"hello").hexdigest()
    assert signature.verify(digest, digest.upper()) is True
    assert signature.verify(digest.upper(), digest) is True


def test_verify_true_with_surrounding_whitespace_on_received() -> None:
    digest = hashlib.md5(b"hello").hexdigest()
    assert signature.verify(digest, f"  {digest}\n") is True


def test_verify_false_for_tampered_hex() -> None:
    digest = hashlib.md5(b"hello").hexdigest()
    tampered = "f" + digest[1:] if not digest.startswith("f") else "0" + digest[1:]
    assert signature.verify(digest, tampered) is False


def test_verify_false_for_non_ascii_received_without_raising() -> None:
    """A malformed/hostile ``sign_string`` with non-ASCII bytes must fail
    closed, not raise. ``hmac.compare_digest`` raises ``TypeError`` on
    non-ASCII strings, and ``received`` is untrusted wire input from the
    webhook — an uncaught ``TypeError`` here would break every Click
    request instead of just this bad one."""
    digest = hashlib.md5(b"hello").hexdigest()
    assert len(digest) == 32
    assert signature.verify(digest, "héllo" + digest[5:]) is False


# --- secret_for_service ---


def test_secret_for_service_returns_web_secret_for_web_id(_click_env: None) -> None:
    assert signature.secret_for_service(108149) == "web-secret-abc"


def test_secret_for_service_returns_bot_secret_for_bot_id(_click_env: None) -> None:
    assert signature.secret_for_service(108150) == "bot-secret-xyz"


def test_secret_for_service_returns_none_for_unknown_id(_click_env: None) -> None:
    assert signature.secret_for_service(999999) is None


def test_secret_for_service_returns_none_when_matching_secret_is_blank(
    monkeypatch: pytest.MonkeyPatch, _clear_settings_cache: None
) -> None:
    monkeypatch.setenv("CLICK_SERVICE_ID_WEB", "108149")
    monkeypatch.setenv("CLICK_SERVICE_ID_BOT", "108150")
    monkeypatch.setenv("CLICK_SECRET_KEY_WEB", "")
    monkeypatch.setenv("CLICK_SECRET_KEY_BOT", "bot-secret-xyz")
    cfg.get_settings.cache_clear()

    assert signature.secret_for_service(108149) is None


def test_secret_for_service_returns_none_when_ids_unconfigured(
    monkeypatch: pytest.MonkeyPatch, _clear_settings_cache: None
) -> None:
    monkeypatch.setenv("CLICK_SERVICE_ID_WEB", "")
    monkeypatch.setenv("CLICK_SERVICE_ID_BOT", "")
    cfg.get_settings.cache_clear()

    assert signature.secret_for_service(108149) is None
