"""The machine-API wire format, exercised without a database (M2, Task 2).

``signing`` is the one home for the canonical string and the digest third
parties implement against, and ``auth.address_allowed`` / ``auth.request_target``
are the pure halves of the IP filter and the request-line read. All are pure
functions, so their edges are cheapest to pin here;
``tests/integration/test_merchant_api_auth.py`` covers them in place.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest
from yupay.modules.merchants import signing
from yupay.modules.merchants.auth import address_allowed


def _msg(**over: object) -> bytes:
    fields: dict[str, object] = {
        "timestamp": "1757000000",
        "method": "GET",
        "raw_path": "/merchant/v1/orders",
        "raw_query": "",
        "body": b"",
    }
    fields.update(over)
    return signing.canonical_message(**fields)  # type: ignore[arg-type]


def test_key_id_and_secret_are_prefixed_and_fit_their_columns() -> None:
    key_id = signing.new_key_id()
    secret = signing.new_secret()
    assert key_id.startswith(signing.KEY_ID_PREFIX)
    assert secret.startswith(signing.SECRET_PREFIX)
    assert len(key_id) <= 48  # merchant_api_keys.key_id is String(48)
    assert key_id != signing.new_key_id()
    assert secret != signing.new_secret()


# ---------- the canonical string ----------


def test_the_canonical_message_is_the_documented_five_fields() -> None:
    message = signing.canonical_message(
        timestamp="1757000000",
        method="post",
        raw_path="/merchant/v1/orders",
        raw_query="dry_run=1",
        body=b'{"a":1}',
    )
    digest = hashlib.sha256(b'{"a":1}').hexdigest()
    assert message == f"1757000000\nPOST\n/merchant/v1/orders\ndry_run=1\n{digest}".encode()


def test_an_empty_body_and_query_are_still_present_as_fields() -> None:
    empty = hashlib.sha256(b"").hexdigest()
    assert _msg() == f"1757000000\nGET\n/merchant/v1/orders\n\n{empty}".encode()


def test_the_timestamp_is_signed_exactly_as_sent() -> None:
    """Not re-formatted from an int — a client sending "01757" signs "01757"."""
    assert _msg(timestamp="01757000000").startswith(b"01757000000\n")


@pytest.mark.parametrize(
    "change",
    [
        {"timestamp": "1757000001"},
        {"method": "POST"},
        {"raw_path": "/merchant/v1/other"},
        {"raw_query": "limit=100000"},
        {"body": b"{}"},
    ],
)
def test_every_field_changes_the_signature(change: dict[str, object]) -> None:
    base = signing.expected_signature("ypms_x", _msg())
    assert signing.expected_signature("ypms_x", _msg(**change)) != base


def test_a_percent_encoded_newline_cannot_forge_a_field_boundary() -> None:
    """The delimiter hole the raw-form + body-hash design closes.

    A path carrying ``%0A`` stays three characters wide in the signed string,
    so it cannot be read as the end of the path field and the start of the
    query field. Both readings must produce different bytes.
    """
    smuggled = _msg(raw_path="/merchant/v1/_probe%0Alimit=100000", raw_query="")
    split = _msg(raw_path="/merchant/v1/_probe", raw_query="limit=100000")
    assert smuggled != split
    assert b"\n" not in smuggled.split(b"\n")[2]  # the path field carries no LF


def test_the_body_is_signed_as_a_hash_so_every_field_is_lf_free() -> None:
    """A body containing newlines cannot shift the field boundaries."""
    message = _msg(body=b"a\nb\nc")
    assert message.count(b"\n") == 4  # exactly the four separators
    assert message.endswith(hashlib.sha256(b"a\nb\nc").hexdigest().encode())


def test_body_digest_is_plain_sha256() -> None:
    assert signing.body_digest(b"") == hashlib.sha256(b"").hexdigest()
    assert signing.body_digest(b"x") == hashlib.sha256(b"x").hexdigest()


# ---------- the HMAC ----------


def test_the_secret_keys_the_hmac_directly_with_no_derivation_step() -> None:
    """Recomputed independently: an ordinary Stripe/AWS-shaped signature."""
    secret = "ypms_example-secret"
    message = _msg()
    assert (
        signing.expected_signature(secret, message)
        == hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    )
    assert signing.signature_matches(secret, message, signing.expected_signature(secret, message))


def test_a_different_secret_does_not_verify() -> None:
    message = _msg()
    assert not signing.signature_matches(
        "ypms_other", message, signing.expected_signature("ypms_x", message)
    )


def test_signature_matches_tolerates_case_and_whitespace() -> None:
    expected = signing.expected_signature("ypms_x", _msg())
    assert signing.signature_matches("ypms_x", _msg(), f"  {expected.upper()}  ")


@pytest.mark.parametrize(
    "provided",
    [
        "é" * 64,  # non-ASCII: compare_digest would raise TypeError -> 500
        "е" * 64,  # Cyrillic е, a plausible copy-paste homoglyph
        "z" * 64,  # right length, not hex
        "ab" * 31,  # 62 chars
        "ab" * 33,  # 66 chars
        "",
        " ",
        "0x" + "a" * 62,
    ],
)
def test_a_malformed_signature_is_rejected_and_never_raises(provided: str) -> None:
    """C1: ``hmac.compare_digest`` raises ``TypeError`` on a non-ASCII ``str``.

    Without the shape check that is an unauthenticated 500 with a traceback
    into Sentry, and it distinguishes malformed input from bad credentials —
    which is exactly what the module promises it never does.
    """
    assert signing.signature_matches("ypms_x", _msg(), provided) is False


# ---------- the IP allowlist ----------


def test_an_absent_or_empty_allowlist_means_no_filter() -> None:
    assert address_allowed(None, "203.0.113.9")
    assert address_allowed([], "203.0.113.9")


def test_the_allowlist_matches_hosts_and_cidr_blocks() -> None:
    allowlist = ["198.51.100.7", "203.0.113.0/24", "2001:db8::/32"]
    assert address_allowed(allowlist, "198.51.100.7")
    assert address_allowed(allowlist, "203.0.113.255")
    assert address_allowed(allowlist, "2001:db8::1")
    assert not address_allowed(allowlist, "198.51.100.8")
    assert not address_allowed(allowlist, "203.0.114.1")
    assert not address_allowed(allowlist, "2001:db9::1")


def test_a_host_address_carrying_a_prefix_is_read_as_its_network() -> None:
    assert address_allowed(["203.0.113.5/24"], "203.0.113.200")


def test_an_unreadable_caller_address_never_matches() -> None:
    """``client_ip`` returns ``"unknown"`` when the transport has no peer."""
    assert not address_allowed(["203.0.113.0/24"], "unknown")
    assert not address_allowed(["203.0.113.0/24"], "")


def test_one_unparseable_entry_does_not_disable_the_rest() -> None:
    assert address_allowed(["not-an-address", "203.0.113.0/24"], "203.0.113.9")
    assert not address_allowed(["not-an-address"], "203.0.113.9")
