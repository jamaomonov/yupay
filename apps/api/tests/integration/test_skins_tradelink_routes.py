"""``/skins/tradelink``: the advisory check, and the saved link (plan 3a, Task 2)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from yupay.core import config as cfg

from tests.integration.test_skins_admin_pricing import _login_user

pytestmark = pytest.mark.asyncio

LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1039652352&token=LBCWEQ8s"


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CS2_SKINS_ENABLED", "true")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


class _Wax:
    def __init__(self, info: str | None) -> None:
        self.info = info

    async def check_tradelink(self, url: str) -> str | None:
        return self.info


class _Steam:
    async def trade_hold_days(self, steam_id: int, token: str) -> int | None:
        return 0


def _use(monkeypatch: pytest.MonkeyPatch, info: str | None) -> None:
    from yupay.modules.skins import tradelink_routes  # after the app: routes import deps

    monkeypatch.setattr(tradelink_routes, "_checkers", lambda: (_Wax(info), _Steam()))


async def test_the_check_names_the_problem(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, "Inventory is private")
    r = await integration_client.post("/api/v1/skins/tradelink/check", json={"url": LINK})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": False, "reason": "private"}


async def test_a_malformed_link_is_invalid_not_an_error(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, None)
    r = await integration_client.post("/api/v1/skins/tradelink/check", json={"url": "nope"})
    assert r.json() == {"ok": False, "reason": "invalid"}


async def test_a_guest_cannot_save_a_link(integration_client: AsyncClient) -> None:
    r = await integration_client.put(
        "/api/v1/skins/tradelink", json={"url": LINK}, headers={"Idempotency-Key": "k" * 16}
    )
    assert r.status_code == 401


async def test_a_signed_in_customer_saves_and_reads_their_link(
    integration_client: AsyncClient,
) -> None:
    auth = {"Authorization": f"Bearer {await _login_user(integration_client, tg_id=920_001)}"}
    empty = await integration_client.get("/api/v1/skins/tradelink", headers=auth)
    assert empty.json() == {"url": None}
    put = await integration_client.put(
        "/api/v1/skins/tradelink",
        json={"url": f" {LINK} "},
        headers={**auth, "Idempotency-Key": "save-trade-link-000001"},
    )
    assert put.status_code == 200, put.text
    got = await integration_client.get("/api/v1/skins/tradelink", headers=auth)
    assert got.json() == {"url": LINK}


async def test_saving_needs_an_idempotency_key(integration_client: AsyncClient) -> None:
    auth = {"Authorization": f"Bearer {await _login_user(integration_client, tg_id=920_002)}"}
    r = await integration_client.put("/api/v1/skins/tradelink", json={"url": LINK}, headers=auth)
    assert r.status_code in (400, 422)


CSM = "https://api.csmarket.test/api/v1/public"


@pytest.fixture
def _csmarket(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """ADR-0098: csmarket answers the check; Steam's own hold check stays ours."""
    from yupay.core.redis import get_redis  # noqa: F401 - the app's redis is real here
    from yupay.modules.skins import tradelink_routes

    monkeypatch.setenv("CS2_SKINS_SOURCE", "csmarket")
    monkeypatch.setenv("CSMARKET_API_KEY", "csm_test")
    monkeypatch.setenv("CSMARKET_BASE_URL", CSM)
    monkeypatch.setattr(tradelink_routes, "_SteamHold", _Steam)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.mark.parametrize(
    ("verdict", "reason", "expected"),
    [
        ("ok", None, {"ok": True, "reason": None}),
        ("bad", "private_inventory", {"ok": False, "reason": "private"}),
        ("bad", "trade_ban", {"ok": False, "reason": "trade_ban"}),
        ("bad", "hold", {"ok": False, "reason": "hold"}),
        ("bad", "invalid_link", {"ok": False, "reason": "invalid"}),
        ("unavailable", None, {"ok": True, "reason": "unavailable"}),
    ],
)
async def test_csmarket_answers_the_check_when_it_is_the_source(
    integration_client: AsyncClient,
    _csmarket: None,
    verdict: str,
    reason: str | None,
    expected: dict[str, object],
) -> None:
    import respx
    from yupay.core.redis import get_redis

    redis = get_redis()
    await redis.delete("skins:tradelink:breaker")
    async for key in redis.scan_iter("skins:tradelink:*"):
        await redis.delete(key)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{CSM}/tradelink/check").respond(
            200, json={"verdict": verdict, "reason": reason}
        )
        r = await integration_client.post("/api/v1/skins/tradelink/check", json={"url": LINK})
    assert r.status_code == 200, r.text
    assert r.json() == expected
    assert route.calls.last.request.headers["Authorization"] == "Bearer csm_test"
