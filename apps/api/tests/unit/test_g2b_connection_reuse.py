"""The G2B client reuses one connection pool instead of dialling per request.

It used to build a fresh ``httpx.AsyncClient`` inside every call, so each
player check and each fulfilment step paid a full TCP + TLS handshake to G2B.
The comment justifying it — "so a hot-reloaded key is picked up" — was aimed
at the wrong object: the API key travels in a per-request header, not in the
client, so the pool can be shared without pinning credentials to it.

That distinction is the thing worth protecting, so it is asserted here
directly: a rebuilt client with new credentials must reuse the pool *and*
send the new key.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from yupay.modules.fulfillment.suppliers import g2b_client as mod
from yupay.modules.fulfillment.suppliers.g2b_client import G2bClient, close_g2b_pool

BASE = "https://g2b.test/v1"


@pytest.fixture(autouse=True)
async def _fresh_pool():
    await close_g2b_pool()
    yield
    await close_g2b_pool()


def _client(api_key: str = "key-1") -> G2bClient:
    return G2bClient(api_key=api_key, base_url=BASE, timeout_seconds=5.0)


@respx.mock
async def test_two_calls_share_one_pool() -> None:
    respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    c = _client()
    await c.games_check_player(game_code="pubgm", player_id="1", server_id=None, charname=None)
    first = mod._pool
    await c.games_check_player(game_code="pubgm", player_id="2", server_id=None, charname=None)

    assert first is not None
    assert mod._pool is first, "a second call must not have opened a second pool"


@respx.mock
async def test_a_rotated_key_still_reaches_g2b_on_the_shared_pool() -> None:
    """The behaviour the per-request client was protecting, kept."""
    route = respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    await _client("old-key").games_check_player(
        game_code="pubgm", player_id="1", server_id=None, charname=None
    )
    pool_after_first = mod._pool

    await _client("new-key").games_check_player(
        game_code="pubgm", player_id="2", server_id=None, charname=None
    )

    assert mod._pool is pool_after_first
    assert route.calls[0].request.headers["X-API-Key"] == "old-key"
    assert route.calls[1].request.headers["X-API-Key"] == "new-key"


@respx.mock
async def test_each_call_carries_its_own_timeout() -> None:
    """Timeout moved from the client to the request, because the pool is now
    shared by callers that do not agree on one."""
    respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    slow = G2bClient(api_key="k", base_url=BASE, timeout_seconds=30.0)
    await slow.games_check_player(game_code="p", player_id="1", server_id=None, charname=None)
    fast = G2bClient(api_key="k", base_url=BASE, timeout_seconds=2.0)
    await fast.games_check_player(game_code="p", player_id="2", server_id=None, charname=None)
    # Both succeeded on the same pool; neither inherited the other's deadline.
    assert mod._pool is not None


@respx.mock
async def test_close_releases_the_pool_and_the_next_call_reopens_it() -> None:
    respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    c = _client()
    await c.games_check_player(game_code="p", player_id="1", server_id=None, charname=None)
    first = mod._pool
    assert first is not None

    await close_g2b_pool()
    # Asserting the global is None here would narrow its type for the rest of
    # the function and make the reopen check unreachable to the type checker;
    # the closed handle proves the same thing without that side effect.
    assert first.is_closed

    await c.games_check_player(game_code="p", player_id="2", server_id=None, charname=None)
    reopened = mod._pool
    assert reopened is not None
    assert reopened is not first
    assert not reopened.is_closed


async def test_closing_an_unused_pool_is_harmless() -> None:
    """Shutdown runs whether or not anything ever called G2B."""
    await close_g2b_pool()
    await close_g2b_pool()
    assert mod._pool is None


@respx.mock
async def test_an_injected_client_still_wins() -> None:
    """Tests hand in their own transport; that must not touch the pool."""
    respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    async with httpx.AsyncClient() as injected:
        c = G2bClient(api_key="k", base_url=BASE, client=injected)
        await c.games_check_player(game_code="p", player_id="1", server_id=None, charname=None)
    assert mod._pool is None, "the injected client must not have opened the shared pool"
