"""Unit tests for the SSRF-safe image URL validator.

Pure functions — no DB, no HTTP. Covers the SSRF finding: catalog
``image_url``/``logo_url``/``hero_image_url`` are fetched server-side by
Next's ``/_next/image`` optimizer (see ``apps/web/next.config.ts``), so an
unvalidated URL could be pointed at internal infrastructure. The Pydantic
wiring of these functions into the admin write schemas is covered in
``test_catalog_admin_schemas.py``; the G2B import's use of the optional
variant is covered in ``test_integrations_sanitize_image_url.py``.
"""

from __future__ import annotations

import pytest
from yupay.modules.catalog.image_url_safety import (
    validate_optional_public_image_url,
    validate_public_image_url,
)

# ---------- validate_public_image_url ----------


def test_accepts_a_normal_https_cdn_url() -> None:
    url = "https://cdn.example.com/x.png"
    assert validate_public_image_url(url) == url


def test_rejects_plain_http_metadata_ip() -> None:
    with pytest.raises(ValueError, match="https"):
        validate_public_image_url("http://169.254.169.254/")


def test_rejects_https_localhost() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        validate_public_image_url("https://localhost/x")


def test_rejects_https_private_ipv4() -> None:
    with pytest.raises(ValueError, match="blocked network"):
        validate_public_image_url("https://10.0.0.1/x")


def test_rejects_ipv6_site_local() -> None:
    """``fec0::/10`` — the one family both this and the connect-time table missed.

    Python excludes it from ``is_private`` *and* ``is_global``, so the old
    hand-written condition here let it through. This file and
    ``test_outbound_ssrf`` now assert the same family off the same table.
    """
    with pytest.raises(ValueError, match="blocked network"):
        validate_public_image_url("https://[fec0::1]/x")


def test_rejects_file_scheme() -> None:
    with pytest.raises(ValueError, match="https"):
        validate_public_image_url("file:///etc/passwd")


@pytest.mark.parametrize(
    "url",
    [
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata, https this time
        "https://172.16.0.5/x",  # RFC1918 172.16/12
        "https://192.168.1.1/x",  # RFC1918 192.168/16
        "https://127.0.0.1/x",  # loopback 127/8
        "https://[::1]/x",  # IPv6 loopback
        "https://[fc00::1]/x",  # IPv6 ULA fc00::/7
        "https://[fe80::1]/x",  # IPv6 link-local fe80::/10
        "https://[fec0::1]/x",  # IPv6 site-local fec0::/10 — RFC 3879, and
        # neither ``is_private`` nor ``is_global`` in Python, so it needs its
        # own entry in the shared table (M3a Task 2 review)
        "https://100.64.0.1/x",  # carrier-grade NAT, caught by the catch-all
        "https://sub.internal/x",  # internal-only TLD
        "https://box.local/x",  # mDNS TLD
        "https://2130706433/x",  # bare-integer IPv4 == 127.0.0.1
        "gopher://169.254.169.254/x",  # non-http(s) scheme
    ],
)
def test_rejects_ssrf_targets(url: str) -> None:
    with pytest.raises(ValueError, match=r"https|not allowed|blocked network"):
        validate_public_image_url(url)


def test_rejects_malformed_url_with_no_host() -> None:
    with pytest.raises(ValueError, match="host"):
        validate_public_image_url("https:///no-host")


# ---------- validate_optional_public_image_url ----------


def test_optional_passes_through_none() -> None:
    assert validate_optional_public_image_url(None) is None


def test_optional_passes_through_empty_string() -> None:
    """ "" is the established "clear this field" convention on the *Update
    schemas (admin_service.update_brand et al. only skip ``None``) — it must
    not be rejected or rewritten."""
    assert validate_optional_public_image_url("") == ""


def test_optional_still_validates_a_real_value() -> None:
    with pytest.raises(ValueError, match="blocked network"):
        validate_optional_public_image_url("https://10.0.0.1/x")
