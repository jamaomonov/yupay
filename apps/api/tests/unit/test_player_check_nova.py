"""The NOVA fallback for the player check.

Two rules this file exists to lock:

* the fallback runs only when the primary answered ``error``;
* it can say ``valid`` or ``error``, never ``invalid`` — only ``invalid``
  blocks Pay (ADR-0031), and a supplier we consult precisely because we have no
  primary verdict may not be the sole basis for refusing a paying customer.
"""

from __future__ import annotations

from typing import Any

import pytest

# Imported first, and as a package rather than reaching straight for
# `yupay.modules.integrations.routes`: that module's own top-level import of
# `yupay.api.v1.deps` walks back through `yupay.api.v1` -> `integrations.api`
# -> `integrations.routes` to resolve `admin_router`/`router`. Entering the
# cycle from `routes` first leaves it mid-import when the walk comes back
# around, so `admin_router` isn't defined yet -> ImportError. Entering via
# `yupay.api.v1` lets that same walk finish `routes` before anything asks it
# for an attribute.
import yupay.api.v1  # noqa: F401
from yupay.modules.fulfillment.suppliers.nova_client import NovaValidation
from yupay.modules.integrations import player_check as pc
from yupay.modules.integrations import player_check_nova as pcn
from yupay.modules.integrations import routes as integration_routes
from yupay.modules.integrations.player_check_nova import fallback_for_brand, fallback_for_steam

# ---------- fakes -------------------------------------------------------


class _FakeRedis:
    """Enough of the client surface for both the cache and the breaker (see
    ``test_supplier_breaker.py``'s fake — this is the same shape, shared here
    because one test exercises both the cache and the breaker together)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        return True

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    async def incr(self, key: str) -> int:
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            n += self.store.pop(k, None) is not None
        return n


class _Settings:
    """Just the two fields the fallback reads off ``get_settings()``."""

    def __init__(self, *, enabled: bool = True, timeout: float = 4.0) -> None:
        self.nova_player_check_enabled = enabled
        self.nova_check_timeout_seconds = timeout


class _ScriptedNovaClient:
    """A NOVA client whose two advisory endpoints answer from a script, or raise."""

    def __init__(
        self,
        *,
        validate_answers: list[NovaValidation] | None = None,
        steam_answers: list[bool] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._validate_answers = list(validate_answers or [])
        self._steam_answers = list(steam_answers or [])
        self._raises = raises
        self.validate_calls: list[dict[str, Any]] = []
        self.steam_calls: list[str] = []

    async def validate_id(
        self, *, category_id: str, fields: dict[str, str], timeout: float | None = None
    ) -> NovaValidation:
        self.validate_calls.append(
            {"category_id": category_id, "fields": fields, "timeout": timeout}
        )
        if self._raises is not None:
            raise self._raises
        return self._validate_answers.pop(0)

    async def check_steam_login(self, steam_login: str, *, timeout: float | None = None) -> bool:
        self.steam_calls.append(steam_login)
        if self._raises is not None:
            raise self._raises
        return self._steam_answers.pop(0)


class _FakeNovaFulfiller:
    """Just enough of ``NovaFulfiller`` the fallback uses: ``_client()``."""

    def __init__(self, client: _ScriptedNovaClient) -> None:
        self._client_obj = client

    def _client(self) -> _ScriptedNovaClient:
        return self._client_obj


class _Recorder:
    """Stands in for the module logger, keeping everything it was handed.

    Not ``caplog``/``structlog.testing.capture_logs``: ``configure_logging``
    sets ``cache_logger_on_first_use``, so a module-level logger bound earlier
    in the session keeps its old processor chain and a capture comes back
    empty (see ``test_outbound_ssrf.py`` and ``test_metrics_labels.py``, which
    document and work around the same trap). Swapping the logger itself is
    the one way this suite reliably sees what was logged.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _record(self, event: str, **fields: Any) -> None:
        self.calls.append((event, fields))

    debug = info = warning = error = exception = _record  # type: ignore[assignment]

    def rendered(self) -> str:
        return "\n".join(f"{event} {fields!r}" for event, fields in self.calls)

    def events(self) -> list[str]:
        return [event for event, _ in self.calls]


class _Env:
    """One test's wiring: fake redis shared by the cache and the breaker,
    fake settings, a swappable fulfiller-or-none, and a log recorder."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.redis = _FakeRedis()
        self.settings = _Settings()
        self.recorder = _Recorder()
        self.fulfiller_calls = 0
        self._fulfiller: _FakeNovaFulfiller | None = None

        monkeypatch.setattr(pcn, "get_redis", lambda: self.redis)
        monkeypatch.setattr(pc, "get_redis", lambda: self.redis)
        monkeypatch.setattr("yupay.modules.integrations.breaker.get_redis", lambda: self.redis)
        monkeypatch.setattr(pcn, "get_settings", lambda: self.settings)
        monkeypatch.setattr(pcn, "logger", self.recorder)

        def _fulfiller_or_none() -> _FakeNovaFulfiller | None:
            self.fulfiller_calls += 1
            return self._fulfiller

        monkeypatch.setattr(integration_routes, "_nova_fulfiller_or_none", _fulfiller_or_none)

    def set_fulfiller(self, fulfiller: _FakeNovaFulfiller | None) -> None:
        self._fulfiller = fulfiller


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> _Env:
    return _Env(monkeypatch)


# ---------- fallback_for_brand -------------------------------------------


async def test_brand_absent_from_nova_validate_is_error_with_no_client_built(
    env: _Env,
) -> None:
    out = await fallback_for_brand(
        brand_slug="a-brand-nova-does-not-cover", player_id="p1", server_id=None
    )
    assert out.status == "error"
    assert env.fulfiller_calls == 0


async def test_kill_switch_disables_the_fallback_with_no_call(env: _Env) -> None:
    env.settings.nova_player_check_enabled = False
    client = _ScriptedNovaClient(
        validate_answers=[NovaValidation(valid=True, player_name="x", region=None)]
    )
    env.set_fulfiller(_FakeNovaFulfiller(client))

    out = await fallback_for_brand(brand_slug="pubg-mobile", player_id="p1", server_id=None)

    assert out.status == "error"
    assert env.fulfiller_calls == 0
    assert client.validate_calls == []


async def test_a_matching_region_is_valid(env: _Env) -> None:
    client = _ScriptedNovaClient(
        validate_answers=[NovaValidation(valid=True, player_name="blood moon", region="Russia")]
    )
    env.set_fulfiller(_FakeNovaFulfiller(client))

    out = await fallback_for_brand(brand_slug="mobile-legends-ru", player_id="p1", server_id=None)

    assert out.status == "valid"
    assert out.name == "blood moon"
    # Their *validate* id, never the top-up id (`mobile_legends_ru`).
    assert client.validate_calls[0]["category_id"] == "mobile_legends"


async def test_region_mismatch_is_error_and_logs_a_warning(env: _Env) -> None:
    client = _ScriptedNovaClient(
        validate_answers=[NovaValidation(valid=True, player_name="blood moon", region="Kazakhstan")]
    )
    env.set_fulfiller(_FakeNovaFulfiller(client))

    out = await fallback_for_brand(brand_slug="mobile-legends-ru", player_id="p1", server_id=None)

    assert out.status == "error"
    assert "player_check_fallback_region_mismatch" in env.recorder.events()


async def test_missing_region_on_a_brand_that_expects_one_is_error(env: _Env) -> None:
    """The guard needs positive evidence, not the absence of contrary evidence."""
    client = _ScriptedNovaClient(
        validate_answers=[NovaValidation(valid=True, player_name="blood moon", region=None)]
    )
    env.set_fulfiller(_FakeNovaFulfiller(client))

    out = await fallback_for_brand(brand_slug="mobile-legends-ru", player_id="p1", server_id=None)

    assert out.status == "error"


async def test_a_negative_nova_verdict_is_error_not_invalid(env: _Env) -> None:
    client = _ScriptedNovaClient(
        validate_answers=[NovaValidation(valid=False, player_name=None, region=None)]
    )
    env.set_fulfiller(_FakeNovaFulfiller(client))

    out = await fallback_for_brand(brand_slug="pubg-mobile", player_id="p1", server_id=None)

    assert out.status == "error"


async def test_a_raising_client_is_error_and_the_breaker_records_a_failure(env: _Env) -> None:
    client = _ScriptedNovaClient(raises=RuntimeError("connection reset"))
    env.set_fulfiller(_FakeNovaFulfiller(client))

    out = await fallback_for_brand(brand_slug="pubg-mobile", player_id="p1", server_id=None)

    assert out.status == "error"
    assert env.redis.store.get("breaker:nova:player_check:fails") == "1"


async def test_breaker_open_short_circuits_with_no_call(env: _Env) -> None:
    env.redis.store["breaker:nova:player_check:open"] = "1"
    client = _ScriptedNovaClient(
        validate_answers=[NovaValidation(valid=True, player_name="x", region=None)]
    )
    env.set_fulfiller(_FakeNovaFulfiller(client))

    out = await fallback_for_brand(brand_slug="pubg-mobile", player_id="p1", server_id=None)

    assert out.status == "error"
    assert client.validate_calls == []


async def test_a_valid_result_is_cached_and_an_error_result_is_not(env: _Env) -> None:
    client = _ScriptedNovaClient(
        validate_answers=[NovaValidation(valid=True, player_name="Neo", region=None)]
    )
    env.set_fulfiller(_FakeNovaFulfiller(client))

    first = await fallback_for_brand(brand_slug="pubg-mobile", player_id="p-valid", server_id=None)
    assert first.status == "valid"
    assert len(client.validate_calls) == 1

    second = await fallback_for_brand(brand_slug="pubg-mobile", player_id="p-valid", server_id=None)
    assert second.status == "valid"
    assert len(client.validate_calls) == 1, "the second call was served from the cache"

    error_client = _ScriptedNovaClient(
        validate_answers=[
            NovaValidation(valid=False, player_name=None, region=None),
            NovaValidation(valid=False, player_name=None, region=None),
        ]
    )
    env.set_fulfiller(_FakeNovaFulfiller(error_client))

    e1 = await fallback_for_brand(brand_slug="pubg-mobile", player_id="p-error", server_id=None)
    assert e1.status == "error"
    e2 = await fallback_for_brand(brand_slug="pubg-mobile", player_id="p-error", server_id=None)
    assert e2.status == "error"
    assert len(error_client.validate_calls) == 2, "an error result must never be cached"


async def test_the_server_value_travels_as_zone_id_not_server_id(env: _Env) -> None:
    client = _ScriptedNovaClient(
        validate_answers=[NovaValidation(valid=True, player_name="x", region=None)]
    )
    env.set_fulfiller(_FakeNovaFulfiller(client))

    await fallback_for_brand(brand_slug="pubg-mobile", player_id="p1", server_id="7001")

    fields = client.validate_calls[0]["fields"]
    assert fields == {"player_id": "p1", "zone_id": "7001"}


# ---------- fallback_for_steam --------------------------------------------


async def test_fallback_for_steam_can_refill_true_is_valid(env: _Env) -> None:
    client = _ScriptedNovaClient(steam_answers=[True])
    env.set_fulfiller(_FakeNovaFulfiller(client))

    out = await fallback_for_steam(steam_login="gaben")

    assert out.status == "valid"


async def test_fallback_for_steam_can_refill_false_is_error_not_invalid(env: _Env) -> None:
    """``can_refill: false`` says NOVA cannot refill the account — weaker than
    "no such login" and never a rejection."""
    client = _ScriptedNovaClient(steam_answers=[False])
    env.set_fulfiller(_FakeNovaFulfiller(client))

    out = await fallback_for_steam(steam_login="gaben")

    assert out.status == "error"


async def test_fallback_for_steam_a_raising_client_is_error(env: _Env) -> None:
    client = _ScriptedNovaClient(raises=RuntimeError("connection reset"))
    env.set_fulfiller(_FakeNovaFulfiller(client))

    out = await fallback_for_steam(steam_login="gaben")

    assert out.status == "error"


# ---------- PII -------------------------------------------------------------


async def test_no_log_line_carries_the_raw_identifier(env: _Env) -> None:
    client = _ScriptedNovaClient(raises=RuntimeError("connection reset"))
    env.set_fulfiller(_FakeNovaFulfiller(client))

    await fallback_for_brand(brand_slug="pubg-mobile", player_id="51234567", server_id=None)
    env.set_fulfiller(
        _FakeNovaFulfiller(_ScriptedNovaClient(raises=RuntimeError("connection reset")))
    )
    await fallback_for_steam(steam_login="a-secret-steam-login")

    rendered = env.recorder.rendered()
    assert "51234567" not in rendered
    assert "a-secret-steam-login" not in rendered


async def test_a_customer_typo_does_not_open_the_circuit(env: _Env) -> None:
    """Their ``422`` is "could not confirm this id" — a mistyped player id.

    The client raises on it, so without discrimination three typos in a row
    would silence the fallback for every brand, during the G2B outage that is
    the only time this code runs at all. The same goes for a ``404``, which is
    a wrong `category_id` in our own table.
    """
    from yupay.modules.fulfillment.suppliers.nova_client import NovaError

    for status in (400, 404, 409, 422):
        env.redis.store.clear()
        client = _ScriptedNovaClient(raises=NovaError("could not confirm", status=status))
        env.set_fulfiller(_FakeNovaFulfiller(client))

        out = await fallback_for_brand(brand_slug="pubg-mobile", player_id="p1", server_id=None)

        assert out.status == "error"
        assert env.redis.store.get("breaker:nova:player_check:fails") is None, status


async def test_their_own_outage_does_open_the_circuit(env: _Env) -> None:
    """A 5xx, a rejected key and a disabled subscription all count: none of
    them will fix itself inside the next call, and each is a wasted round trip
    on a customer's spinner."""
    from yupay.modules.fulfillment.suppliers.nova_client import NovaError

    for status in (500, 503, 401, 403):
        env.redis.store.clear()
        client = _ScriptedNovaClient(raises=NovaError("upstream", status=status))
        env.set_fulfiller(_FakeNovaFulfiller(client))

        out = await fallback_for_brand(brand_slug="pubg-mobile", player_id="p1", server_id=None)

        assert out.status == "error"
        assert env.redis.store.get("breaker:nova:player_check:fails") == "1", status


async def test_their_error_text_never_carries_back_the_identifier(env: _Env) -> None:
    """Their message is theirs, not ours.

    An API that answers "player 51234567 not found" would put a customer's id
    in our log through the error field (§9). We know exactly what we sent, so
    it comes back out.
    """
    from yupay.modules.fulfillment.suppliers.nova_client import NovaError

    client = _ScriptedNovaClient(
        raises=NovaError("player 51234567 not found on zone 6618", status=422)
    )
    env.set_fulfiller(_FakeNovaFulfiller(client))

    out = await fallback_for_brand(
        brand_slug="mobile-legends-ru", player_id="51234567", server_id="6618"
    )

    assert out.status == "error"
    rendered = env.recorder.rendered()
    assert "51234567" not in rendered
    assert "6618" not in rendered
    assert "not found" in rendered
