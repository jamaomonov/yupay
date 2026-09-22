"""POST /catalog/brands/{slug}/check-player — storefront player verification."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import httpx
import pytest
import respx
import structlog.testing
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.integrations.models import SkuSupplierMapping

pytestmark = pytest.mark.integration

G2B_BASE = "https://g2b.test/v1"
WAXPEER_BASE = "https://waxpeer.test/v1"


@pytest.fixture(autouse=True)
def _g2b_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Same wiring as ``test_integrations_g2b_game_endpoints.py``: the g2b
    fulfiller only reports ``available`` when ``G2B_API_KEY`` is set."""
    monkeypatch.setenv("G2B_API_KEY", "test-key")
    monkeypatch.setenv("G2B_BASE_URL", G2B_BASE)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _waxpeer_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Same wiring, for the waxpeer branch: ``WaxpeerFulfiller.available``
    only reports ``True`` when ``WAXPEER_API_KEY`` is set (see
    ``test_waxpeer_fulfiller.py``'s ``_env`` fixture)."""
    monkeypatch.setenv("WAXPEER_API_KEY", "test-waxpeer-key")
    monkeypatch.setenv("WAXPEER_BASE_URL", WAXPEER_BASE)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture
async def client(integration_client: AsyncClient) -> AsyncClient:
    """Alias to the suite's DB-wired ASGI client, named ``client`` to match
    the brief's test bodies. Both ``guard_ip`` and the player-check response
    cache in ``player_check.py`` key off real Redis (see
    ``tests/integration/test_auth_ip_guard.py`` for the established explicit-
    flush convention this mirrors) — flush both namespaces so repeated local
    runs stay deterministic:

    - the ``check_player`` ip-guard bucket for this fixed ASGITransport IP
      (127.0.0.1);
    - the ``playercheck:g2b:pubgm:*`` cache keys, since
      ``test_check_player_valid`` and ``test_g2b_error_degrades_to_error_status``
      both check the same ``player_id`` ("51234567") against the same
      ``game_code`` ("pubgm") — without this flush the second test would read
      back the first test's cached ``{status: valid}`` instead of exercising the
      G2B-failure path;
    - the ``playercheck:waxpeer:*`` cache keys, for the same reason on the
      Steam-login tests below (they reuse the login "gaben" across the
      valid/invalid/error cases).
    """
    from yupay.core.redis import get_redis

    redis = get_redis()
    await redis.delete("auth:ipguard:check_player:127.0.0.1")
    stale_cache_keys = await redis.keys("playercheck:g2b:pubgm:*")
    stale_cache_keys += await redis.keys("playercheck:waxpeer:*")
    if stale_cache_keys:
        await redis.delete(*stale_cache_keys)
    return integration_client


@pytest.fixture
async def seed_g2b_product(db_session: AsyncSession) -> Product:
    """A checkable product: ``required_fields`` opts into a g2b check and an
    active g2b game mapping resolves ``game_code='pubgm'``."""
    category = Category(
        id=new_id(),
        slug="games-pc-check",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="pubgm-check",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="PUBG Mobile")],
    )
    product = Product(
        id=new_id(),
        slug="pubgm-uc-check",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[
            {
                "key": "player_id",
                "label": {"ru": "ID"},
                "type": "text",
                "check": {"provider": "g2b"},
            }
        ],
        translations=[ProductTranslation(locale="ru", name="PUBG Mobile UC")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="pubgm-60uc-check",
        denomination="60",
        region="WW",
        price_usd=Decimal("1.00"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    # Flush the SKU in its own commit before the mapping: SQLAlchemy's unit of
    # work only orders cross-table INSERTs via declared `relationship()`s, and
    # `Sku`/`SkuSupplierMapping` aren't linked by one (only a raw FK column) —
    # a single combined commit can emit the mapping INSERT before the sku
    # INSERT and trip the FK constraint.
    mapping = SkuSupplierMapping(
        sku_id=sku.id,
        supplier_slug="g2b",
        kind="game",
        external_product_id="pubgm",
        external_variant_id="60UC",
        is_active=True,
    )
    db_session.add(mapping)
    await db_session.commit()
    return product


@pytest.fixture
async def seed_plain_product(db_session: AsyncSession) -> Product:
    """A product with no ``check`` descriptor on any field — not checkable."""
    category = Category(
        id=new_id(),
        slug="vouchers-plain-check",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Ваучеры")],
    )
    brand = Brand(
        id=new_id(),
        slug="steam-plain-check",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Steam")],
    )
    product = Product(
        id=new_id(),
        slug="steam-giftcard-plain-check",
        brand_id=brand.id,
        kind="voucher",
        sort_order=10,
        active=True,
        required_fields=[{"key": "email", "label": {"ru": "Почта"}, "type": "text"}],
        translations=[ProductTranslation(locale="ru", name="Steam Gift Card")],
    )
    db_session.add_all([category, brand, product])
    await db_session.commit()
    return product


@pytest.fixture
async def seed_waxpeer_product(db_session: AsyncSession) -> Product:
    """A checkable product whose player-id field routes to waxpeer: a Steam
    wallet top-up SKU with a ``check.provider == "waxpeer"`` field. Unlike
    the g2b fixture, no ``SkuSupplierMapping`` is needed — the waxpeer branch
    validates the login directly, it doesn't resolve a game_code."""
    category = Category(
        id=new_id(),
        slug="steam-topups-check",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Пополнения")],
    )
    brand = Brand(
        id=new_id(),
        slug="steam-wallet-check",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Steam Wallet")],
    )
    product = Product(
        id=new_id(),
        slug="steam-wallet-topup-check",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[
            {
                "key": "steam_login",
                "label": {"ru": "Логин Steam"},
                "type": "text",
                "check": {"provider": "waxpeer"},
            }
        ],
        translations=[ProductTranslation(locale="ru", name="Steam Wallet Top-up")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="steam-wallet-variable-check",
        denomination="variable",
        region="WW",
        price_usd=Decimal("1.00"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return product


@respx.mock
async def test_check_player_valid(client: httpx.AsyncClient, seed_g2b_product: Product) -> None:
    respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    r = await client.post(
        "/api/v1/catalog/brands/pubgm-check/check-player",
        json={"player_id": "51234567", "server_id": None},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "valid", "name": "Neo"}


@respx.mock
async def test_check_player_invalid(client: httpx.AsyncClient, seed_g2b_product: Product) -> None:
    # Real G2B behaviour: an invalid player id comes back as HTTP 400 carrying
    # the verdict body (not a 200). The client unwraps that to a normal verdict,
    # and the endpoint reports status="invalid" — NOT "error".
    respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(400, json={"valid": "invalid", "name": ""})
    )
    r = await client.post(
        "/api/v1/catalog/brands/pubgm-check/check-player",
        json={"player_id": "9"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "invalid"
    assert body["name"] is None


@respx.mock
async def test_check_player_real_400_error_is_error_not_invalid(
    client: httpx.AsyncClient, seed_g2b_product: Product
) -> None:
    # A 400 WITHOUT a verdict body (e.g. a malformed request / unknown game) is
    # a genuine fault, not an invalid id → status="error".
    respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(400, json={"message": "bad request"})
    )
    r = await client.post(
        "/api/v1/catalog/brands/pubgm-check/check-player",
        json={"player_id": "9"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


@respx.mock
async def test_g2b_error_degrades_to_error_status(client, seed_g2b_product: Product) -> None:
    respx.post(url__regex=r".*/games/checkPlayerId").mock(side_effect=httpx.ConnectError("down"))
    r = await client.post(
        "/api/v1/catalog/brands/pubgm-check/check-player",
        json={"player_id": "51234567"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


@pytest.fixture
async def seed_split_brand(db_session: AsyncSession) -> str:
    """One brand, two products, two G2B games — the pre-ADR-0079 MLBB shape."""
    category = Category(
        id=new_id(),
        slug="games-split-check",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="mlbb-split-check",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="MLBB")],
    )
    field = [
        {"key": "player_id", "label": {"ru": "ID"}, "type": "text", "check": {"provider": "g2b"}}
    ]
    products = [
        Product(
            id=new_id(),
            slug=f"mlbb-{tag}-check",
            brand_id=brand.id,
            kind="top_up",
            sort_order=i,
            active=True,
            required_fields=field,
            translations=[ProductTranslation(locale="ru", name=f"MLBB {tag}")],
        )
        for i, tag in enumerate(("global", "ru"))
    ]
    skus = [
        Sku(
            id=new_id(),
            product_id=p.id,
            sku_code=f"mlbb-{p.slug}-60",
            denomination="60",
            region="WW",
            price_usd=Decimal("1.00"),
            sort_order=1,
            active=True,
        )
        for p in products
    ]
    db_session.add_all([category, brand, *products, *skus])
    await db_session.commit()
    db_session.add_all(
        [
            SkuSupplierMapping(
                sku_id=skus[0].id,
                supplier_slug="g2b",
                kind="game",
                external_product_id="mlbb",
                external_variant_id="60",
                is_active=True,
            ),
            SkuSupplierMapping(
                sku_id=skus[1].id,
                supplier_slug="g2b",
                kind="game",
                external_product_id="mlbb_ru",
                external_variant_id="60",
                is_active=True,
            ),
        ]
    )
    await db_session.commit()
    return brand.slug


@respx.mock
async def test_a_brand_spanning_two_games_checks_nothing(
    client: httpx.AsyncClient, seed_split_brand: str
) -> None:
    """Picking one of two games would validate a player against the wrong
    region and call a good id `invalid`. The only honest answer is `error`."""
    route = respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    with structlog.testing.capture_logs() as logs:
        r = await client.post(
            f"/api/v1/catalog/brands/{seed_split_brand}/check-player",
            json={"player_id": "51234567"},
        )
    assert r.status_code == 200
    assert r.json()["status"] == "error"
    assert not route.called, "no supplier call on an ambiguous brand"
    assert any(e["event"] == "player_check_brand_spans_games" for e in logs)


@pytest.fixture
async def seed_split_brand_with_retired_region(db_session: AsyncSession) -> str:
    """Same shape as ``seed_split_brand``, but the second (retired) region's
    product is ``active=False`` — its mapping is still active, the way a
    catalog would look if the product were deactivated without also
    deactivating the now-orphaned ``sku_supplier_mapping`` row. Only one game
    code is a candidate here, so the brand must answer a real verdict."""
    category = Category(
        id=new_id(),
        slug="games-split-retired-check",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="mlbb-split-retired-check",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="MLBB")],
    )
    field = [
        {"key": "player_id", "label": {"ru": "ID"}, "type": "text", "check": {"provider": "g2b"}}
    ]
    products = [
        Product(
            id=new_id(),
            slug=f"mlbb-{tag}-retired-check",
            brand_id=brand.id,
            kind="top_up",
            sort_order=i,
            active=(tag == "global"),
            required_fields=field,
            translations=[ProductTranslation(locale="ru", name=f"MLBB {tag}")],
        )
        for i, tag in enumerate(("global", "ru"))
    ]
    skus = [
        Sku(
            id=new_id(),
            product_id=p.id,
            sku_code=f"mlbb-{p.slug}-60",
            denomination="60",
            region="WW",
            price_usd=Decimal("1.00"),
            sort_order=1,
            active=True,
        )
        for p in products
    ]
    db_session.add_all([category, brand, *products, *skus])
    await db_session.commit()
    db_session.add_all(
        [
            SkuSupplierMapping(
                sku_id=skus[0].id,
                supplier_slug="g2b",
                kind="game",
                external_product_id="mlbb",
                external_variant_id="60",
                is_active=True,
            ),
            SkuSupplierMapping(
                sku_id=skus[1].id,
                supplier_slug="g2b",
                kind="game",
                external_product_id="mlbb_ru",
                external_variant_id="60",
                is_active=True,
            ),
        ]
    )
    await db_session.commit()
    return brand.slug


@respx.mock
async def test_a_retired_product_s_mapping_does_not_block_the_live_one(
    client: httpx.AsyncClient, seed_split_brand_with_retired_region: str
) -> None:
    """A deactivated region product left with an active mapping must not make
    the brand look ambiguous forever — only the live product's code counts."""
    route = respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    r = await client.post(
        f"/api/v1/catalog/brands/{seed_split_brand_with_retired_region}/check-player",
        json={"player_id": "51234567"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "valid"
    assert route.call_count == 1


async def test_not_checkable_product_422(client, seed_plain_product: Product) -> None:
    # NOTE: the task brief's global constraints and design spec both say "→ 400"
    # for a non-checkable brand. `player_check.check_player_for_brand_id` raises
    # `ValidationError`, which this codebase's global error handler maps to
    # **422** everywhere (`yupay.core.errors.ValidationError.status_code = 422`;
    # see `tests/integration/test_payments_routes.py:370` and
    # `tests/integration/test_inventory_sourcing_routes.py:355` for the same
    # established convention). Asserting the real, already-established status
    # code here rather than the brief's stale 400.
    r = await client.post(
        "/api/v1/catalog/brands/steam-plain-check/check-player",
        json={"player_id": "1"},
    )
    assert r.status_code == 422


async def test_unknown_brand_404(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/v1/catalog/brands/no-such-brand/check-player",
        json={"player_id": "1"},
    )
    assert r.status_code == 404
    assert r.json()["code"] == "brand_not_found"


async def test_old_product_route_is_gone(client) -> None:
    """The route moved to the brand path (ADR-0079); the old product-scoped
    one no longer exists at all — FastAPI 404s with no matching route."""
    r = await client.post(
        "/api/v1/catalog/products/00000000-0000-0000-0000-000000000000/check-player",
        json={"player_id": "1"},
    )
    assert r.status_code == 404


@respx.mock
async def test_rate_limited_after_threshold(client, seed_g2b_product, monkeypatch) -> None:
    """The guard still trips — at this bucket's own ceiling, not the shared one.

    Pinned explicitly rather than counting on a default, because the ceiling
    that matters here is deliberately no longer ``auth_ip_guard_max``: this is
    an advisory lookup a customer runs while filling in the order form, and
    Uzbek mobile carriers put many subscribers behind one address, so the
    brute-force budget was being spent collectively by strangers.
    """
    monkeypatch.setenv("AUTH_IP_GUARD_BUCKET_MAX", '{"check_player": 4}')
    cfg.get_settings.cache_clear()

    respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    url = "/api/v1/catalog/brands/pubgm-check/check-player"
    last = None
    for _ in range(8):
        last = await client.post(url, json={"player_id": "51234567"})
    assert last is not None
    assert last.status_code == 429
    cfg.get_settings.cache_clear()


async def test_check_player_is_not_throttled_at_the_login_threshold(client) -> None:
    """Guards the regression this change exists to prevent: someone raising
    the shared max for the storefront's sake, and loosening `login` with it."""
    from yupay.modules.auth.ip_guard import bucket_limit

    settings = cfg.get_settings()
    assert bucket_limit(settings, "check_player") > bucket_limit(settings, "login")


@respx.mock
async def test_player_id_never_logged_plaintext(client, seed_g2b_product) -> None:
    """The brief's original body asserts against ``caplog.text``, but this
    codebase's ``configure_logging()`` (``yupay.core.logging``) wires structlog
    with ``structlog.PrintLoggerFactory()``, which writes straight to stdout and
    never touches the stdlib ``logging`` module — so ``caplog`` (which hooks a
    handler onto stdlib logging) stays empty no matter what is logged. Verified
    with a throwaway probe: `logger.info(...)` calls during a request left
    ``caplog.text == ""`` and ``caplog.records == []``. Asserting
    ``secret not in caplog.text`` against an always-empty string is vacuously
    true — it would pass even if the raw player_id were logged, which fails the
    "verify real behavior" bar. ``structlog.testing.capture_logs()`` captures the
    actual emitted event dicts regardless of the configured logger factory
    (confirmed against this same request: it captured the ``player_check`` event
    with ``player_id_hash`` and no raw id), so it is the real-behavior-verifying
    substitute for the brief's ``caplog`` fixture here.
    """
    respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    secret = "51234567"
    with structlog.testing.capture_logs() as cap:
        r = await client.post(
            "/api/v1/catalog/brands/pubgm-check/check-player",
            json={"player_id": secret},
        )
    assert r.status_code == 200
    log_text = " ".join(repr(entry) for entry in cap)
    assert secret not in log_text


@respx.mock
async def test_steam_login_valid(client: httpx.AsyncClient, seed_waxpeer_product: Product) -> None:
    """A supported login answers status "valid"."""
    respx.get(url__regex=r".*/steam-topup/validate").mock(
        return_value=httpx.Response(200, json={"success": True, "valid": True})
    )
    r = await client.post(
        "/api/v1/catalog/brands/steam-wallet-check/check-player",
        json={"player_id": "gaben-valid"},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "valid", "name": None}


@respx.mock
async def test_steam_login_is_checked_via_nova_when_it_is_configured(
    client: httpx.AsyncClient, seed_waxpeer_product: Product, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 2026-09-22 swap, end to end. When NOVA is configured it answers
    first, and a real answer from it must never reach Waxpeer at all —
    `/steam-topup/validate` is deliberately left unmocked, so a fallthrough
    to it would fail on the network, not on an assertion, exactly like the
    catalogue-sync tests that pin "the unmapped one is never asked"."""
    monkeypatch.setenv("NOVA_API_KEY", "test-nova-key")
    monkeypatch.setenv("NOVA_BASE_URL", "https://nova.test")
    cfg.get_settings.cache_clear()
    respx.post(url__regex=r".*/api/v2/steam-topup/check-login").mock(
        return_value=httpx.Response(200, json={"ok": True, "can_refill": True})
    )
    r = await client.post(
        "/api/v1/catalog/brands/steam-wallet-check/check-player",
        json={"player_id": "gaben-valid"},
    )
    cfg.get_settings.cache_clear()
    assert r.status_code == 200
    assert r.json() == {"status": "valid", "name": None}


@respx.mock
async def test_steam_login_invalid(
    client: httpx.AsyncClient, seed_waxpeer_product: Product
) -> None:
    """An unsupported login answers status "invalid", not an error — the
    customer mistyped, nothing is broken."""
    respx.get(url__regex=r".*/steam-topup/validate").mock(
        return_value=httpx.Response(
            200, json={"success": True, "valid": False, "msg": "account not found"}
        )
    )
    r = await client.post(
        "/api/v1/catalog/brands/steam-wallet-check/check-player",
        json={"player_id": "gaben-invalid"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "invalid"
    assert body["name"] is None


@respx.mock
async def test_steam_check_upstream_failure_is_error(
    client: httpx.AsyncClient, seed_waxpeer_product: Product
) -> None:
    """Waxpeer unreachable answers status "error" so the UI blames us, not the
    customer, and never blocks checkout."""
    respx.get(url__regex=r".*/steam-topup/validate").mock(side_effect=httpx.ConnectError("down"))
    r = await client.post(
        "/api/v1/catalog/brands/steam-wallet-check/check-player",
        json={"player_id": "gaben-error"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


@pytest.fixture
async def _clean_circuit():
    """The breaker lives in real Redis, so a tripped circuit would otherwise
    leak into the next test — and into the next local run."""
    from yupay.core.redis import get_redis

    keys = ("breaker:g2b:player_check:fails", "breaker:g2b:player_check:open")
    redis = get_redis()
    await redis.delete(*keys)
    yield redis
    await redis.delete(*keys)


@pytest.fixture
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the client's 1→2→4→8s retry sleeps.

    What is under test is the breaker, not the backoff, and paying the real
    15s per failing call would put these two tests alone near a minute.
    """

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr("yupay.modules.fulfillment.suppliers.g2b_client.asyncio.sleep", _instant)


@respx.mock
async def test_breaker_stops_paying_the_backoff_for_every_customer(
    client, seed_g2b_product: Product, _clean_circuit, _no_backoff
) -> None:
    """After a run of upstream failures the check stops calling G2B at all.

    Without the breaker every one of these customers sits through the client's
    full retry budget to reach the same verdict. The answer they see is
    identical either way — `error`, which the storefront reads as "couldn't
    check" and never as a bad id — so the wait buys them nothing.
    """
    from yupay.modules.integrations import player_check as pc

    route = respx.post(url__regex=r".*/games/checkPlayerId").mock(
        side_effect=httpx.ConnectError("down")
    )

    for i in range(pc._BREAKER_THRESHOLD):
        r = await client.post(
            "/api/v1/catalog/brands/pubgm-check/check-player",
            json={"player_id": f"5123456{i}"},
        )
        assert r.json()["status"] == "error"

    assert route.call_count > 0, "the failing calls must really have reached G2B"
    calls_while_closed = route.call_count

    r = await client.post(
        "/api/v1/catalog/brands/pubgm-check/check-player",
        json={"player_id": "51234599"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"
    assert route.call_count == calls_while_closed, (
        "the circuit was open, so this check must not have reached G2B"
    )


@respx.mock
async def test_a_good_check_closes_the_circuit(
    client, seed_g2b_product: Product, _clean_circuit, _no_backoff
) -> None:
    """A recovered supplier must not stay locked out for the rest of the
    cooldown — the probe that gets through has to be able to end the outage."""
    from yupay.modules.integrations import player_check as pc

    redis = _clean_circuit
    route = respx.post(url__regex=r".*/games/checkPlayerId")
    route.mock(side_effect=httpx.ConnectError("down"))
    for i in range(pc._BREAKER_THRESHOLD):
        await client.post(
            "/api/v1/catalog/brands/pubgm-check/check-player",
            json={"player_id": f"5123457{i}"},
        )
    assert await redis.exists("breaker:g2b:player_check:open")

    # In production the cooldown expiring is what lets a probe through;
    # deleting the key is that moment without a 30s sleep.
    await redis.delete("breaker:g2b:player_check:open")
    route.mock(return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"}))

    r = await client.post(
        "/api/v1/catalog/brands/pubgm-check/check-player",
        json={"player_id": "51234588"},
    )
    assert r.json()["status"] == "valid"
    assert not await redis.exists("breaker:g2b:player_check:fails")


async def test_the_db_connection_is_released_before_the_supplier_call(
    client, seed_g2b_product: Product, _clean_circuit
) -> None:
    """A pool connection must not be held across a G2B round trip.

    The pool is twenty connections for the whole process. This check is
    storefront-facing — a customer runs it while filling in the order form —
    and G2B takes 830ms to 4.9s *when healthy*, measured on production. At the
    slow end, four concurrent checks a second occupy every connection, and once
    the twentieth is taken every other endpoint waits `pool_timeout` and then
    500s: browsing, login, checkout, admin, payment webhooks, all at once.

    All the DB work this path needs (the product, its supplier mapping) is done
    before the call, so the connection has no reason to still be checked out.
    """
    from yupay.core.db import get_engine

    seen: list[int] = []

    async def _spy_check_player(**kwargs: object) -> dict[str, object]:
        # `checkedout` lives on QueuePool, which the base Pool type does
        # not declare; the async engine uses one.
        seen.append(get_engine().pool.checkedout())  # type: ignore[attr-defined]
        return {"valid": "valid", "name": "Neo"}

    from yupay.modules.integrations.routes import _g2b_fulfiller_or_none

    fulfiller = _g2b_fulfiller_or_none()
    assert fulfiller is not None
    client_obj = fulfiller._client()
    original = client_obj.games_check_player
    client_obj.games_check_player = _spy_check_player  # type: ignore[method-assign]
    fulfiller._client_override = client_obj

    try:
        r = await client.post(
            "/api/v1/catalog/brands/pubgm-check/check-player",
            json={"player_id": "51230001"},
        )
    finally:
        client_obj.games_check_player = original  # type: ignore[method-assign]
        fulfiller._client_override = None

    assert r.status_code == 200, r.text
    assert seen, "the supplier call never happened — the spy was not reached"
    assert seen[0] == 0, (
        f"{seen[0]} pool connection(s) were still checked out during the G2B call; "
        "a slow supplier therefore consumes the pool and takes the whole API down with it"
    )


@respx.mock
async def test_a_negative_g2b_verdict_is_not_served_from_cache(
    client: httpx.AsyncClient, seed_g2b_product: Product
) -> None:
    """Same policy as the Waxpeer path, at the other cache write site.

    First answer is a negative, second is a positive for the same id. Before
    `_worth_caching` the second request never reached G2B: the `invalid` was
    answered from Redis for 300 s, and `invalid` is the one verdict that blocks
    Pay.
    """
    route = respx.post(url__regex=r".*/games/checkPlayerId").mock(
        side_effect=[
            httpx.Response(400, json={"valid": "invalid", "name": ""}),
            httpx.Response(200, json={"valid": "valid", "name": "Neo"}),
        ]
    )
    url = "/api/v1/catalog/brands/pubgm-check/check-player"

    first = await client.post(url, json={"player_id": "51234567", "server_id": None})
    assert first.json()["status"] == "invalid"

    second = await client.post(url, json={"player_id": "51234567", "server_id": None})
    assert second.json() == {"status": "valid", "name": "Neo"}
    assert route.call_count == 2, "the re-check reached G2B"
