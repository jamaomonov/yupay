"""Steam CDN URLs served from a host our customers can reach.

ByMykel (and Waxpeer's stickers) link images on
``community.akamai.steamstatic.com``, which did not open from Uzbekistan on
2026-09-28 while ``community.fastly.steamstatic.com`` served the identical file
by the same ``/economy/image/<hash>`` path. The host is a setting
(``cs2_skins_image_host``) so it can be switched without a data migration —
rows keep whatever URL the import wrote; the rewrite happens on the way out.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

_STEAM_HOST_SUFFIXES = (".steamstatic.com", ".akamaihd.net")


def steam_image(url: str | None, *, host: str) -> str | None:
    """``url`` with a Steam CDN host replaced by ``host``; anything else unchanged."""
    if not url:
        return url
    parts = urlsplit(url)
    if not parts.hostname or not parts.hostname.endswith(_STEAM_HOST_SUFFIXES):
        return url
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


__all__ = ["steam_image"]
