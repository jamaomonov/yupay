"""The machine-API wire format, exercised without a database (M2, Task 2).

``signing`` is the one home for the canonical string and the digests third
parties implement against, and ``auth.address_allowed`` is the pure half of
the IP filter. Both are pure functions, so their edges are cheapest to pin
here; ``tests/integration/test_merchant_api_auth.py`` covers them in place.
"""

from __future__ import annotations

import hashlib
import hmac

from yupay.modules.merchants import signing
from yupay.modules.merchants.auth import address_allowed


def test_key_id_and_secret_are_prefixed_and_fit_their_columns() -> None:
    key_id = signing.new_key_id()
    secret = signing.new_secret()
    assert key_id.startswith(signing.KEY_ID_PREFIX)
    assert secret.startswith(signing.SECRET_PREFIX)
    assert len(key_id) <= 48  # merchant_api_keys.key_id is String(48)
    assert key_id != signing.new_key_id()
    assert secret != signing.new_secret()


def test_the_signing_key_is_the_sha256_of_the_secret_and_fits_secret_hash() -> None:
    """Pins the derivation third parties must run — see signing's docstring."""
    secret = "ypms_example-secret"
    derived = signing.derive_signing_key(secret)
    assert derived == hashlib.sha256(secret.encode()).hexdigest()
    assert len(derived) == 64  # merchant_api_keys.secret_hash is String(64)


def test_the_canonical_message_is_the_documented_four_fields() -> None:
    message = signing.canonical_message(
        timestamp="1757000000", method="post", path="/merchant/v1/orders", body=b'{"a":1}'
    )
    assert message == b'1757000000\nPOST\n/merchant/v1/orders\n{"a":1}'


def test_an_empty_body_still_ends_with_the_separator() -> None:
    message = signing.canonical_message(
        timestamp="1757000000", method="GET", path="/merchant/v1/me", body=b""
    )
    assert message == b"1757000000\nGET\n/merchant/v1/me\n"


def test_the_timestamp_is_signed_exactly_as_sent() -> None:
    """Not re-formatted from an int — a client sending "01757" signs "01757"."""
    assert signing.canonical_message(
        timestamp="01757000000", method="GET", path="/x", body=b""
    ).startswith(b"01757000000\n")


def test_signature_matches_accepts_the_expected_digest() -> None:
    key = signing.derive_signing_key("ypms_x")
    message = signing.canonical_message(
        timestamp="1", method="GET", path="/merchant/v1/me", body=b""
    )
    expected = hmac.new(key.encode(), message, hashlib.sha256).hexdigest()
    assert signing.expected_signature(key, message) == expected
    assert signing.signature_matches(key, message, expected)


def test_signature_matches_tolerates_case_and_whitespace_but_nothing_else() -> None:
    key = signing.derive_signing_key("ypms_x")
    message = signing.canonical_message(timestamp="1", method="GET", path="/x", body=b"")
    expected = signing.expected_signature(key, message)
    assert signing.signature_matches(key, message, f"  {expected.upper()}  ")
    assert not signing.signature_matches(key, message, expected[:-1] + "0")
    assert not signing.signature_matches(key, message, "")
    assert not signing.signature_matches(signing.derive_signing_key("other"), message, expected)


def test_a_different_body_or_path_changes_the_signature() -> None:
    key = signing.derive_signing_key("ypms_x")
    base = signing.canonical_message(timestamp="1", method="POST", path="/a", body=b"{}")
    assert signing.expected_signature(key, base) != signing.expected_signature(
        key, signing.canonical_message(timestamp="1", method="POST", path="/a", body=b"{ }")
    )
    assert signing.expected_signature(key, base) != signing.expected_signature(
        key, signing.canonical_message(timestamp="1", method="POST", path="/b", body=b"{}")
    )
    assert signing.expected_signature(key, base) != signing.expected_signature(
        key, signing.canonical_message(timestamp="2", method="POST", path="/a", body=b"{}")
    )


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
