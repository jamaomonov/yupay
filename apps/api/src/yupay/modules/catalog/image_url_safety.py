"""SSRF-safe validation for catalog image URLs.

``Brand.logo_url``/``Brand.hero_image_url``/``Product.image_url``/``Sku.image_url``
are plain, unvalidated strings that end up as the ``url=`` query parameter Next.js's
``/_next/image`` optimizer fetches *server-side* (see ``apps/web/next.config.ts``).
Without validation, an admin (or the G2B supplier import — see
``yupay.modules.integrations.service.import_game``) could point one of these fields
at an internal address and turn the image optimizer into an SSRF proxy against our
own infrastructure (e.g. the cloud metadata endpoint, or another service on the
private network).

:func:`validate_public_image_url` is the single source of truth for this check,
called both from the admin write-path Pydantic schemas
(:mod:`yupay.modules.catalog.admin_schemas`) and from the G2B import
(:mod:`yupay.modules.integrations.service`).

Residual risk — read before assuming this closes the finding:

* This only rejects URLs whose host is *already* an IP literal in a blocked
  range (or a handful of well-known non-routable names). It cannot detect
  **DNS rebinding**: a hostname that resolves to a public IP right now (when
  this validator runs) but to a private/loopback/metadata IP at the moment
  Next's image optimizer actually fetches it. Closing that residual risk
  requires the fetcher itself to re-resolve and re-check the IP at request
  time (or pin the resolved IP), which is Next's image optimizer's
  responsibility, not this validator's — Next does not offer a hook for it.
* It only understands standard dotted-decimal / colon-hex IP notation (plus
  bare-integer IPv4, e.g. ``http://2130706433/``). Other obfuscations
  (octal/hex-per-octet forms) are not normalised here; treat this as raising
  the bar, not as a hermetic filter.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

# mDNS / common internal-only TLDs. None of these should ever resolve on the
# public internet, so there is no legitimate catalog-image use for them.
_BLOCKED_HOST_SUFFIXES = (".local", ".localhost", ".internal")
_BLOCKED_HOSTS = frozenset({"localhost", "internal"})


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Best-effort parse of ``host`` as an IP literal, or ``None`` if it isn't one.

    Handles standard dotted-decimal/colon-hex notation directly, plus the
    common bare-integer IPv4 bypass (``http://2130706433/`` == 127.0.0.1)
    that ``ipaddress.ip_address`` alone does not accept.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if host.isdigit():
        try:
            return ipaddress.IPv4Address(int(host))
        except (ValueError, ipaddress.AddressValueError):
            return None
    return None


def validate_public_image_url(url: str) -> str:
    """Reject ``url`` unless it is an ``https`` URL pointing at a public host.

    Intended for a non-empty, already-stripped candidate URL — callers own
    the "blank/omitted is fine, don't call this" decision (see the
    ``if not v: return v`` short-circuit in the admin schema validators).

    Blocks:
        * Any non-``https`` scheme (``http``, ``file``, ``gopher``, ``ftp``, ...).
        * ``localhost`` / ``internal`` and anything under ``*.local`` /
          ``*.localhost`` / ``*.internal``.
        * A host that is an IP literal in a private, loopback, link-local
          (this covers the ``169.254.169.254`` cloud metadata address),
          reserved, multicast, or unspecified range — i.e.
          ``ipaddress.ip_address(...).is_private`` and friends, which
          together cover RFC1918 (10/8, 172.16/12, 192.168/16), 127/8,
          ``::1``, ``fc00::/7`` and ``fe80::/10``.

    Args:
        url: A non-empty candidate image URL.

    Returns:
        ``url`` unchanged, once it has passed every check.

    Raises:
        ValueError: The URL is missing/malformed or targets a blocked host.
            Pydantic ``field_validator``s turn this straight into a 422.
    """
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError("image URL must use https")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("image URL must have a host")
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise ValueError(f"image URL host {host!r} is not allowed")
    ip = _parse_ip(host)
    if ip is not None and (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        raise ValueError(f"image URL host {host!r} resolves to a blocked network")
    return url


def validate_optional_public_image_url(url: str | None) -> str | None:
    """``validate_public_image_url`` for the common "blank means don't touch /
    no image" optional-field case.

    ``None`` (field omitted/never set) and ``""`` (the explicit "clear this
    field" convention used by ``BrandUpdate``/``ProductUpdate``/``SkuUpdate``
    — see ``admin_service.update_brand`` et al.) both pass through
    unvalidated and unchanged; only a truthy string is checked.
    """
    if not url:
        return url
    return validate_public_image_url(url)


__all__ = [
    "validate_optional_public_image_url",
    "validate_public_image_url",
]
