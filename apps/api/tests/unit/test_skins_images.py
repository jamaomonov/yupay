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
