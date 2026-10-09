"""Steam CDN host rewrite: ByMykel links point at an Akamai host that does not
open from Uzbekistan (measured 2026-09-28); the same path serves from fastly."""

from __future__ import annotations

from yupay.modules.skins.images import steam_image

H = "https://community.akamai.steamstatic.com/economy/image/abc123"


def test_steam_hosts_are_rewritten_to_the_configured_one() -> None:
    assert steam_image(H, host="community.fastly.steamstatic.com") == (
        "https://community.fastly.steamstatic.com/economy/image/abc123"
    )
    assert (
        steam_image(
            "https://steamcommunity-a.akamaihd.net/economy/image/abc123/360fx360f",
            host="community.fastly.steamstatic.com",
        )
        == "https://community.fastly.steamstatic.com/economy/image/abc123/360fx360f"
    )


def test_other_urls_and_none_pass_through() -> None:
    assert steam_image("https://raw.githubusercontent.com/x.png", host="h") == (
        "https://raw.githubusercontent.com/x.png"
    )
    assert steam_image(None, host="h") is None
    assert steam_image("not a url", host="h") == "not a url"


def test_sticker_icon_paths_go_to_the_cdn_twin() -> None:
    """``/apps/730/icons/…`` on community.* redirects to the Steam home page (2026-10-09)."""
    from yupay.modules.skins.images import steam_image

    url = (
        "https://community.akamai.steamstatic.com/apps/730/icons/econ/stickers/"
        "cluj2015/tit_foil.e2e7639957898245dd6a4c5fae7d68d1a8f0bd66.png"
    )
    assert steam_image(url, host="community.fastly.steamstatic.com") == url.replace(
        "community.akamai.steamstatic.com", "cdn.fastly.steamstatic.com"
    )
    # An item image keeps the configured host.
    item = "https://community.akamai.steamstatic.com/economy/image/abc"
    assert steam_image(item, host="community.fastly.steamstatic.com") == (
        "https://community.fastly.steamstatic.com/economy/image/abc"
    )
    # A host that is not a community.* one is used as configured.
    other = steam_image(url, host="cdn.example.steamstatic.com")
    assert other is not None
    assert other.startswith("https://cdn.example.steamstatic.com/apps/")
