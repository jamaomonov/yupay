"""Unit tests for ``yupay.modules.gifts.checkout``.

Covers ``is_gift_sku`` (duck-typed sku_code check), ``parse_invite_url``'s
accept/reject table, and every numbered rule in ``price_gift_line``'s
docstring: the feature flag, the four required snapshot fields, the
upstream app/package lookup, the zone price lookup, the margin-applied
expected price, the ±2 % tolerance band, and the enriched snapshot. No real
DB, Redis, or upstream HTTP: ``get_app`` and ``load_margin_percent`` are
monkeypatched directly on the ``checkout`` module, and ``get_settings`` is
swapped for a small stand-in exposing just the fields this module reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import NotFoundError, UpstreamUnavailableError, ValidationError
from yupay.modules.gifts import checkout

#: ``price_gift_line`` only ever forwards ``db`` to ``load_margin_percent``,
#: which every test here monkeypatches to ignore it — so a typed stand-in
#: (never a real session) is all any call site needs.
_DB = cast(AsyncSession, object())


@dataclass(frozen=True)
class _Settings:
    steam_gifts_enabled: bool = True
    steam_gifts_regions: str = "CIS,RU,KZ"
    steam_gifts_region_default: str = "CIS"


_DEAD_CELLS: dict[str, Any] = {
    "id": 588650,
    "name": "Dead Cells",
    "packages": [
        {
            "id": 1,
            "name": "Standard Edition",
            "prices": [
                {"zone": "CIS", "price": 1.00},
                {"zone": "RU", "price": None},
            ],
        }
    ],
}

_VALID_INVITE = "https://steamcommunity.com/profiles/76561198000000000"


def _line_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "app_id": 588650,
        "package_id": 1,
        "region": "CIS",
        "invite_url": _VALID_INVITE,
    }
    data.update(overrides)
    return data


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> _Settings:
    settings = _Settings()
    monkeypatch.setattr(checkout, "get_settings", lambda: settings)
    return settings


@pytest.fixture(autouse=True)
def _margin(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _load(db: object) -> Decimal:
        return Decimal("10")

    monkeypatch.setattr(checkout, "load_margin_percent", _load)


@pytest.fixture(autouse=True)
def _get_app(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _get(app_id: int) -> dict[str, Any]:
        assert app_id == 588650
        return _DEAD_CELLS

    monkeypatch.setattr(checkout, "get_app", _get)


# ---------- is_gift_sku ----------


def test_is_gift_sku_matches_the_steam_gift_sku_code() -> None:
    sku = type("S", (), {"sku_code": checkout.STEAM_GIFT_SKU_CODE})()
    assert checkout.is_gift_sku(sku) is True


def test_is_gift_sku_rejects_any_other_sku_code() -> None:
    sku = type("S", (), {"sku_code": "pubg-uc-60"})()
    assert checkout.is_gift_sku(sku) is False


def test_is_gift_sku_rejects_a_sku_with_no_sku_code_attribute() -> None:
    assert checkout.is_gift_sku(object()) is False


# ---------- parse_invite_url ----------


@pytest.mark.parametrize(
    "value",
    [
        "https://steamcommunity.com/profiles/76561198000000000",
        "https://steamcommunity.com/id/my_vanity-01",
        "https://s.team/p/abcXYZ",
        # missing scheme is tolerated
        "steamcommunity.com/profiles/76561198000000000",
        # trailing slash is tolerated
        "https://steamcommunity.com/profiles/76561198000000000/",
        # surrounding whitespace is stripped
        "  https://steamcommunity.com/id/my_vanity-01  ",
    ],
)
def test_parse_invite_url_accepts_valid_steam_links(value: str) -> None:
    assert checkout.parse_invite_url(value) != ""


def test_parse_invite_url_canonicalizes_a_schemeless_profile_link() -> None:
    result = checkout.parse_invite_url("steamcommunity.com/profiles/76561198000000000/")
    assert result == "https://steamcommunity.com/profiles/76561198000000000"


def test_parse_invite_url_canonicalizes_a_vanity_link() -> None:
    result = checkout.parse_invite_url("  https://steamcommunity.com/id/my_vanity-01  ")
    assert result == "https://steamcommunity.com/id/my_vanity-01"


def test_parse_invite_url_canonicalizes_an_s_team_link() -> None:
    result = checkout.parse_invite_url("s.team/p/abcXYZ")
    assert result == "https://s.team/p/abcXYZ"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not a url at all",
        "https://evil.com/profiles/76561198000000000",
        # steamid64 must be exactly 17 digits
        "https://steamcommunity.com/profiles/12345",
        # vanity must be 2-32 chars of [A-Za-z0-9_-]
        "https://steamcommunity.com/id/a",
        "https://steamcommunity.com/id/" + ("a" * 33),
        "https://steamcommunity.com/id/bad!chars",
        # scheme-injection / downgrade attempts
        "http://steamcommunity.com/profiles/76561198000000000",
        "javascript://steamcommunity.com/profiles/76561198000000000",
        # userinfo smuggling a trusted host into an untrusted one
        "https://steamcommunity.com@evil.com/profiles/76561198000000000",
        # wrong path entirely
        "https://steamcommunity.com/groups/somegroup",
    ],
)
def test_parse_invite_url_rejects_garbage_and_scheme_injection(value: str) -> None:
    with pytest.raises(ValidationError):
        checkout.parse_invite_url(value)


# ---------- price_gift_line: rule 1 - feature flag ----------


async def test_disabled_flag_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checkout, "get_settings", lambda: _Settings(steam_gifts_enabled=False))
    with pytest.raises(ValidationError, match="steam gifts are not available right now"):
        await checkout.price_gift_line(_DB, line_amount_usd=Decimal("1.10"), data=_line_data())


# ---------- price_gift_line: rule 2 - required fields ----------


async def test_missing_app_id_is_rejected() -> None:
    data = _line_data()
    del data["app_id"]
    with pytest.raises(ValidationError):
        await checkout.price_gift_line(_DB, line_amount_usd=Decimal("1.10"), data=data)


async def test_non_int_able_app_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        await checkout.price_gift_line(
            _DB,
            line_amount_usd=Decimal("1.10"),
            data=_line_data(app_id="not-a-number"),
        )


async def test_missing_package_id_is_rejected() -> None:
    data = _line_data()
    del data["package_id"]
    with pytest.raises(ValidationError):
        await checkout.price_gift_line(_DB, line_amount_usd=Decimal("1.10"), data=data)


async def test_region_not_in_offered_zones_is_rejected() -> None:
    with pytest.raises(ValidationError):
        await checkout.price_gift_line(
            _DB, line_amount_usd=Decimal("1.10"), data=_line_data(region="XX")
        )


async def test_invalid_invite_url_is_rejected() -> None:
    with pytest.raises(ValidationError, match="invite_url is not a Steam profile or friend link"):
        await checkout.price_gift_line(
            _DB, line_amount_usd=Decimal("1.10"), data=_line_data(invite_url="garbage")
        )


async def test_invite_url_canonical_form_is_written_back_into_the_snapshot() -> None:
    _, snapshot = await checkout.price_gift_line(
        _DB,
        line_amount_usd=Decimal("1.10"),
        data=_line_data(invite_url="steamcommunity.com/profiles/76561198000000000/"),
    )
    assert snapshot["invite_url"] == "https://steamcommunity.com/profiles/76561198000000000"


# ---------- price_gift_line: rule 3 - app/package lookup ----------


async def test_app_gone_upstream_maps_to_the_generic_unavailable_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(app_id: int) -> dict[str, Any]:
        raise NotFoundError(f"gift app {app_id} not found")

    monkeypatch.setattr(checkout, "get_app", _boom)
    with pytest.raises(ValidationError, match="this game is no longer available"):
        await checkout.price_gift_line(_DB, line_amount_usd=Decimal("1.10"), data=_line_data())


async def test_upstream_unavailable_propagates_uncaught(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(app_id: int) -> dict[str, Any]:
        raise UpstreamUnavailableError("the gifts catalog is temporarily unavailable")

    monkeypatch.setattr(checkout, "get_app", _boom)
    with pytest.raises(UpstreamUnavailableError):
        await checkout.price_gift_line(_DB, line_amount_usd=Decimal("1.10"), data=_line_data())


async def test_unknown_package_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="this game is no longer available"):
        await checkout.price_gift_line(
            _DB,
            line_amount_usd=Decimal("1.10"),
            data=_line_data(package_id=999),
        )


# ---------- price_gift_line: rule 4 - zone price ----------


async def test_region_with_no_price_on_the_package_is_rejected() -> None:
    # RU is an offered zone but this package's RU price is null upstream.
    with pytest.raises(ValidationError, match="this region has no price for the selected edition"):
        await checkout.price_gift_line(
            _DB,
            line_amount_usd=Decimal("1.10"),
            data=_line_data(region="RU"),
        )


# ---------- price_gift_line: rule 5/6 - expected price + tolerance ----------


async def test_amount_is_required() -> None:
    with pytest.raises(ValidationError, match="amount is required for this product"):
        await checkout.price_gift_line(_DB, line_amount_usd=None, data=_line_data())


async def test_price_within_tolerance_is_accepted_and_bills_the_server_price() -> None:
    # supplier 1.00 * 1.10 margin = 1.10 expected. Client sends 1.12 (~1.8% off).
    price, _ = await checkout.price_gift_line(
        _DB, line_amount_usd=Decimal("1.12"), data=_line_data()
    )
    # Rule 8: the server price is billed even inside the tolerance band.
    assert price == Decimal("1.10")


async def test_price_drifted_beyond_tolerance_is_rejected_with_expected_amount() -> None:
    # expected is 1.10 (1.00 supplier * 1.10 margin); 1.20 is a 9% drift,
    # well past the 2% tolerance band.
    with pytest.raises(ValidationError) as excinfo:
        await checkout.price_gift_line(_DB, line_amount_usd=Decimal("1.20"), data=_line_data())
    # The codebase convention nests the payload under an "extra" key on the
    # error object itself (``AppError.__init__(self, detail=None, **extra)``
    # captures the caller's ``extra={...}`` kwarg by that name) — this is
    # what ``app_error_handler`` then merges into the RFC 7807 body.
    assert excinfo.value.extra == {"extra": {"expected_amount_usd": "1.10"}}


# ---------- price_gift_line: rule 7/8 - enriched snapshot ----------


async def test_happy_path_returns_expected_price_and_enriched_snapshot() -> None:
    price, snapshot = await checkout.price_gift_line(
        _DB, line_amount_usd=Decimal("1.10"), data=_line_data()
    )
    assert price == Decimal("1.10")
    assert snapshot["app_name"] == "Dead Cells"
    assert snapshot["package_name"] == "Standard Edition"
    assert snapshot["supplier_price_usd"] == "1.0"
    assert snapshot["invite_url"] == _VALID_INVITE
