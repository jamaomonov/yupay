"""Steam ``IEconService/GetTradeHoldDurations`` for a trade link (plan 3a, Task 2)."""

from __future__ import annotations

import httpx
import pytest
import respx
from yupay.modules.auth.steam import trade_hold_days

URL = "https://api.steampowered.com/IEconService/GetTradeHoldDurations/v1/"


def _body(their_seconds: int) -> dict[str, object]:
    return {
        "response": {
            "my_escrow": {"escrow_end_duration_seconds": 0},
            "their_escrow": {"escrow_end_duration_seconds": their_seconds},
            "both_escrow": {"escrow_end_duration_seconds": their_seconds},
        }
    }


@respx.mock
async def test_an_account_with_an_authenticator_has_no_hold() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=_body(0)))
    days = await trade_hold_days(76561198999918080, "LBCWEQ8s", api_key="K")
    assert days == 0
    sent = route.calls.last.request.url.params
    assert sent["steamid_target"] == "76561198999918080"
    assert sent["trade_offer_access_token"] == "LBCWEQ8s"


@respx.mock
async def test_a_held_account_reports_whole_days() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=_body(15 * 86400)))
    assert await trade_hold_days(1, "t", api_key="K") == 15


@respx.mock
async def test_a_body_without_their_escrow_is_unknown() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={"response": {}}))
    assert await trade_hold_days(1, "t", api_key="K") is None


@respx.mock
async def test_a_steam_error_raises() -> None:
    respx.get(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPError):
        await trade_hold_days(1, "t", api_key="K")
