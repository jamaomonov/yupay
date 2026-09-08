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
* Notation is read the way the **fetcher** reads it, because anything else
  checks a different string from the one that is fetched: the host is
  IDNA-normalised first (so ``ⓛⓞⓒⓐⓛⓗⓞⓢⓣ`` and ``127。0。0。1`` are seen as
  ``localhost`` and ``127.0.0.1``, which is what Node's ``new URL()`` makes of
  them), and IP literals are parsed by the URL standard's IPv4 rules — bare
  integer, octal, hex, short dotted — not only by ``ipaddress``. Still treat
  it as raising the bar rather than as a hermetic filter: it is a
  string-shaped check, and the only real answer is the connect-time one this
  path cannot have.

The rules outgrew the name. :func:`validate_public_https_url` is the generic
form — same checks, a caller-supplied noun for the error message — and
:func:`validate_public_image_url` is the catalog's thin wrapper over it. The
second caller is the merchant webhook URL (M3a Task 1,
``merchants.admin.set_webhook``): sharing this function is what keeps one
blocked-range table in the repo instead of two that drift. It is the
**save-time** half there too, and the DNS-rebinding caveat above applies
unchanged for this function.

What closes that caveat is a fetcher that re-checks the address it actually
connects to, and for the webhook path one now exists:
:mod:`yupay.core.outbound` (M3a Task 2) resolves the host itself, refuses
unless every answer is public, and connects to the address it checked. Read
the two together: this module is the cheap early refusal on the admin write,
that one is the control. **The image path still has no such fetcher** — Next
owns it and offers no hook — so for catalog images this file remains the only
check there is, with the residual risk above intact.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from yupay.core.outbound_addresses import blocked_reason

# mDNS / common internal-only TLDs. None of these should ever resolve on the
# public internet, so there is no legitimate catalog-image use for them.
_BLOCKED_HOST_SUFFIXES = (".local", ".localhost", ".internal")
_BLOCKED_HOSTS = frozenset({"localhost", "internal"})


def normalize_host(host: str) -> str:
    """The host as **Node** will read it, which is what this must classify.

    The fetcher on this path is Next's image optimizer, i.e. Node's WHATWG
    ``new URL()``, which applies IDNA/UTS-46 mapping to the host. Classifying
    the raw ``urlsplit`` hostname therefore checks a different string from the
    one that is fetched: ``https://ⓛⓞⓒⓐⓛⓗⓞⓢⓣ/x.png`` and
    ``https://127。0。0。1/x.png`` are what an attacker writes and
    ``localhost`` / ``127.0.0.1`` are what Node connects to.

    Python's IDNA codec does the same mapping for our purposes — nameprep is
    NFKC plus case folding, and it treats the ideographic and fullwidth full
    stops as label separators — so one call closes the gap. ASCII hosts skip
    it entirely: the codec would also reject spellings the DNS accepts, and an
    ASCII host has nothing to map.

    Args:
        host: ``urlsplit``'s hostname.

    Returns:
        The normalised, lowercased host with any trailing dot removed.

    Raises:
        ValueError: A non-ASCII host that will not encode. Refused rather than
            passed through raw — this is the one path with no connect-time
            re-check, so an unclassifiable host is not a host we will store.
    """
    if host.isascii():
        return host.lower().rstrip(".")
    try:
        return host.encode("idna").decode("ascii").lower().rstrip(".")
    except (UnicodeError, ValueError) as exc:
        raise ValueError("host is not a usable domain name") from exc


def _ipv4_number(part: str) -> int | None:
    """One dotted part as WHATWG's IPv4 parser reads it: hex, octal or decimal.

    ``int(part, base)`` alone is too generous — it accepts underscores, signs
    and surrounding whitespace, none of which Node accepts — so the digits are
    checked against the base first.
    """
    digits, base = part, 10
    if part[:2].lower() == "0x":
        digits, base = part[2:], 16
    elif len(part) > 1 and part[0] == "0":
        digits, base = part[1:], 8
    if digits == "":
        return 0
    allowed = "0123456789abcdef"[:base] if base != 8 else "01234567"
    if not all(character in allowed for character in digits.lower()):
        return None
    return int(digits, base)


def _whatwg_ipv4(host: str) -> ipaddress.IPv4Address | None:
    """WHATWG's IPv4 parser, or ``None`` when the host is a name.

    ``ipaddress`` reads exactly one spelling of an IPv4 address; the URL
    standard reads several, and Node implements the URL standard. Every one of
    ``0x7f.1``, ``0177.0.0.1``, ``127.1`` and ``2130706433`` is 127.0.0.1 to
    ``new URL()`` and a mere hostname to ``ipaddress``, which is how a
    loopback URL used to be storable.

    An out-of-range value returns ``None``: Node rejects the URL outright, so
    nothing fetches it and there is nothing to block.
    """
    parts = host.split(".")
    if len(parts) > 1 and parts[-1] == "":
        parts.pop()
    if not 1 <= len(parts) <= 4:
        return None
    numbers: list[int] = []
    for part in parts:
        number = _ipv4_number(part)
        if number is None:
            return None
        numbers.append(number)
    if any(number > 255 for number in numbers[:-1]):
        return None
    if numbers[-1] >= 256 ** (5 - len(numbers)):
        return None
    value = numbers[-1]
    for index, number in enumerate(numbers[:-1]):
        value += number * 256 ** (3 - index)
    try:
        return ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:  # pragma: no cover -- bounded above
        return None


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Best-effort parse of ``host`` as an IP literal, or ``None`` if it isn't one.

    Standard dotted-decimal/colon-hex notation first, then the URL standard's
    IPv4 forms (:func:`_whatwg_ipv4`) — bare integer, octal, hex and short
    dotted — because those are the ones the fetcher on this path resolves.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return _whatwg_ipv4(host)


def validate_public_https_url(url: str, *, subject: str = "URL") -> str:
    """Reject ``url`` unless it is an ``https`` URL pointing at a public host.

    Intended for a non-empty, already-stripped candidate URL — callers own
    the "blank/omitted is fine, don't call this" decision (see the
    ``if not v: return v`` short-circuit in the admin schema validators).

    Blocks:
        * Any non-``https`` scheme (``http``, ``file``, ``gopher``, ``ftp``, ...).
        * ``localhost`` / ``internal`` and anything under ``*.local`` /
          ``*.localhost`` / ``*.internal``.
        * A host that is an IP literal in any family
          :data:`yupay.core.outbound_addresses.BLOCKED_FAMILIES` names —
          loopback, RFC 1918 private, link-local (which covers the
          ``169.254.169.254`` cloud metadata address), unique-local,
          site-local, multicast, ``0.0.0.0/8``, unspecified and reserved —
          plus anything that is not globally routable, such as carrier-grade
          NAT. That table is shared with the connect-time client rather than
          restated here: two lists drift, and the review that added
          ``fec0::/10`` had to fix it in both.

    Args:
        url: A non-empty candidate URL.
        subject: What the URL is, as it should read in an error message
            ("image URL", "webhook URL"). Only the wording depends on it;
            every rule above is the same for every caller, which is the
            point of having one function.

    Returns:
        ``url`` unchanged, once it has passed every check.

    Raises:
        ValueError: The URL is missing/malformed or targets a blocked host.
            Pydantic ``field_validator``s turn this straight into a 422.
    """
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError(f"{subject} must use https")
    try:
        host = normalize_host(parsed.hostname or "")
    except ValueError as exc:
        raise ValueError(f"{subject} host is not a usable domain name") from exc
    if not host:
        raise ValueError(f"{subject} must have a host")
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise ValueError(f"{subject} host {host!r} is not allowed")
    ip = _parse_ip(host)
    if ip is not None and blocked_reason(ip) is not None:
        raise ValueError(f"{subject} host {host!r} resolves to a blocked network")
    return url


def validate_public_image_url(url: str) -> str:
    """:func:`validate_public_https_url` worded for a catalog image URL.

    Args:
        url: A non-empty candidate image URL.

    Returns:
        ``url`` unchanged, once it has passed every check.

    Raises:
        ValueError: The URL is missing/malformed or targets a blocked host.
    """
    return validate_public_https_url(url, subject="image URL")


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
    "normalize_host",
    "validate_optional_public_image_url",
    "validate_public_https_url",
    "validate_public_image_url",
]
