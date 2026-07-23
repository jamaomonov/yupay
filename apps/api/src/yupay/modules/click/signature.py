"""Click Shop API sign_string: build (Prepare/Complete) and verify.

Click authenticates every Prepare/Complete webhook with an MD5 ``sign_string``
keyed on a per-service ``SECRET_KEY`` — one secret for the web service, a
different one for the Telegram mini-app (bot) service, both sharing one
merchant. This is a new pattern for YuPay: Payme/Uzum authenticate via HTTP
Basic auth, not a request-body MD5 digest, so this module has no exact twin
in those acquirers' code.

This module is pure — no I/O, no DB — beyond reading the two configured
secrets off :func:`yupay.core.config.get_settings`. Every function takes the
**raw wire strings** exactly as Click sent them (e.g. ``form["amount"]``
untouched) and must not reformat, round, or otherwise normalize them: Click's
own MD5 is computed over those exact bytes, so any reformatting here would
produce a hash that never matches Click's.

See ``docs/superpowers/specs/2026-07-23-click-shop-api-design.md`` §6 for the
formulas this module implements.
"""

from __future__ import annotations

import hashlib
import hmac

from yupay.core.config import get_settings


def secret_for_service(service_id: int) -> str | None:
    """Look up the configured ``SECRET_KEY`` for a Click ``service_id``.

    Args:
        service_id: The ``service_id`` field from an inbound Click request.

    Returns:
        ``click_secret_key_web`` if ``service_id`` matches the configured
        ``click_service_id_web``, ``click_secret_key_bot`` if it matches
        ``click_service_id_bot``, or ``None`` if ``service_id`` matches
        neither configured id (including when the corresponding id itself
        is unconfigured, i.e. ``None``) or the matching secret is blank.
        A blank secret is treated the same as "unconfigured" so a
        half-configured service never silently verifies against an empty
        key.
    """
    settings = get_settings()

    if settings.click_service_id_web is not None and service_id == settings.click_service_id_web:
        secret = settings.click_secret_key_web
        return secret if secret else None

    if settings.click_service_id_bot is not None and service_id == settings.click_service_id_bot:
        secret = settings.click_secret_key_bot
        return secret if secret else None

    return None


def prepare_sign(
    *,
    click_trans_id: str,
    service_id: str,
    secret: str,
    merchant_trans_id: str,
    amount: str,
    action: str,
    sign_time: str,
) -> str:
    """Build the MD5 ``sign_string`` Click expects for a Prepare request.

    Args:
        click_trans_id: Click's own transaction id, as received (raw string).
        service_id: The ``service_id`` field, as received (raw string).
        secret: The ``SECRET_KEY`` for this ``service_id`` (see
            :func:`secret_for_service`).
        merchant_trans_id: Our order id, as received (raw string).
        amount: The ``amount`` field, as received — Click's own wire
            formatting (e.g. ``"1000.00"``); never reformatted here.
        action: The ``action`` field, as received (raw string, ``"0"`` for
            Prepare).
        sign_time: The ``sign_time`` field, as received (raw string).

    Returns:
        The lowercase hex MD5 digest of
        ``click_trans_id + service_id + secret + merchant_trans_id + amount
        + action + sign_time``.
    """
    concat = click_trans_id + service_id + secret + merchant_trans_id + amount + action + sign_time
    # MD5 is mandated by Click's Shop API signature scheme — not our choice,
    # and used only to authenticate their webhook, not to protect data at rest.
    return hashlib.md5(concat.encode()).hexdigest()  # noqa: S324


def complete_sign(
    *,
    click_trans_id: str,
    service_id: str,
    secret: str,
    merchant_trans_id: str,
    merchant_prepare_id: str,
    amount: str,
    action: str,
    sign_time: str,
) -> str:
    """Build the MD5 ``sign_string`` Click expects for a Complete request.

    Same formula as :func:`prepare_sign`, with ``merchant_prepare_id``
    inserted immediately after ``merchant_trans_id``.

    Args:
        click_trans_id: Click's own transaction id, as received (raw string).
        service_id: The ``service_id`` field, as received (raw string).
        secret: The ``SECRET_KEY`` for this ``service_id`` (see
            :func:`secret_for_service`).
        merchant_trans_id: Our order id, as received (raw string).
        merchant_prepare_id: The ``merchant_prepare_id`` we issued during
            Prepare, as received back (raw string).
        amount: The ``amount`` field, as received; never reformatted here.
        action: The ``action`` field, as received (raw string, ``"1"`` for
            Complete).
        sign_time: The ``sign_time`` field, as received (raw string).

    Returns:
        The lowercase hex MD5 digest of
        ``click_trans_id + service_id + secret + merchant_trans_id +
        merchant_prepare_id + amount + action + sign_time``.
    """
    concat = (
        click_trans_id
        + service_id
        + secret
        + merchant_trans_id
        + merchant_prepare_id
        + amount
        + action
        + sign_time
    )
    # MD5 is mandated by Click's Shop API signature scheme — see the note in
    # prepare_sign().
    return hashlib.md5(concat.encode()).hexdigest()  # noqa: S324


def verify(expected_hex: str, received: str) -> bool:
    """Constant-time, case-insensitive comparison of a ``sign_string``.

    Args:
        expected_hex: The hex MD5 we computed (see :func:`prepare_sign` /
            :func:`complete_sign`).
        received: The ``sign_string`` field Click sent, as received (may
            carry incidental surrounding whitespace).

    Returns:
        ``True`` if the two digests match, ignoring case and surrounding
        whitespace on ``received``; ``False`` otherwise.
    """
    return hmac.compare_digest(expected_hex.lower(), received.strip().lower())


__all__ = [
    "complete_sign",
    "prepare_sign",
    "secret_for_service",
    "verify",
]
