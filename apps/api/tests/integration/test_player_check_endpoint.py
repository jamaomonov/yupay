"""POST /catalog/products/{id}/check-player — storefront player verification."""

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
        f"/api/v1/catalog/products/{seed_g2b_product.id}/check-player",
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
        f"/api/v1/catalog/products/{seed_g2b_product.id}/check-player",
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
        f"/api/v1/catalog/products/{seed_g2b_product.id}/check-player",
        json={"player_id": "9"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


@respx.mock
async def test_g2b_error_degrades_to_error_status(client, seed_g2b_product: Product) -> None:
    respx.post(url__regex=r".*/games/checkPlayerId").mock(side_effect=httpx.ConnectError("down"))
    r = await client.post(
        f"/api/v1/catalog/products/{seed_g2b_product.id}/check-player",
        json={"player_id": "51234567"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


async def test_two_game_codes_on_one_product_check_nothing(
    client, db_session: AsyncSession, seed_g2b_product: Product
) -> None:
    """A product mapped to two G2B games has no single right answer.

    Region is split across products (ADR-0048), so this is a misconfiguration —
    and the old ``.limit(1)`` picked one arbitrarily, which would verify a
    player against the wrong region's game and report a perfectly good id as
    invalid. No check beats a wrong one: the storefront shows "couldn't check",
    never "wrong id".
    """
    second = Sku(
        id=new_id(),
        product_id=seed_g2b_product.id,
        sku_code="pubgm-325uc-check",
        denomination="325",
        region="RU",
        price_usd=Decimal("5.00"),
        sort_order=20,
        active=True,
    )
    db_session.add(second)
    await db_session.commit()
    db_session.add(
        SkuSupplierMapping(
            sku_id=second.id,
            supplier_slug="g2b",
            kind="game",
            external_product_id="pubgm_ru",
            external_variant_id="325UC",
            is_active=True,
        )
    )
    await db_session.commit()

    r = await client.post(
        f"/api/v1/catalog/products/{seed_g2b_product.id}/check-player",
        json={"player_id": "51234567"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


async def test_not_checkable_product_422(client, seed_plain_product: Product) -> None:
    # NOTE: the task brief's global constraints and design spec both say "→ 400"
    # for a non-checkable product. The already-merged Task 3 service
    # (`player_check.check_player_for_product`) raises `ValidationError`, which
    # this codebase's global error handler maps to **422** everywhere
    # (`yupay.core.errors.ValidationError.status_code = 422`; see
    # `tests/integration/test_payments_routes.py:370` and
    # `tests/integration/test_inventory_sourcing_routes.py:355` for the same
    # established convention). Task 4 only wires the route — changing the
    # module-wide `ValidationError` status code is out of scope and would
    # ripple across every other module that raises it. Asserting the real,
    # already-established status code here rather than the brief's stale 400.
    r = await client.post(
        f"/api/v1/catalog/products/{seed_plain_product.id}/check-player",
        json={"player_id": "1"},
    )
    assert r.status_code == 422


async def test_unknown_product_404(client) -> None:
    r = await client.post(
        "/api/v1/catalog/products/00000000-0000-0000-0000-000000000000/check-player",
        json={"player_id": "1"},
    )
    assert r.status_code == 404


async def test_malformed_product_id_404_not_500(client) -> None:
    """``Product.id`` is a UUID column — a non-UUID path segment must fold
    into the same "not found" contract (ADR-0031), not a raw DBAPIError."""
    r = await client.post(
        "/api/v1/catalog/products/not-a-uuid/check-player",
        json={"player_id": "1"},
    )
    assert r.status_code == 404


@respx.mock
async def test_rate_limited_after_threshold(client, seed_g2b_product) -> None:
    respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    url = f"/api/v1/catalog/products/{seed_g2b_product.id}/check-player"
    last = None
    for _ in range(15):  # window max defaults to 10 (auth_ip_guard_max)
        last = await client.post(url, json={"player_id": "51234567"})
    assert last is not None
    assert last.status_code == 429


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
            f"/api/v1/catalog/products/{seed_g2b_product.id}/check-player",
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
        f"/api/v1/catalog/products/{seed_waxpeer_product.id}/check-player",
        json={"player_id": "gaben-valid"},
    )
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
        f"/api/v1/catalog/products/{seed_waxpeer_product.id}/check-player",
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
        f"/api/v1/catalog/products/{seed_waxpeer_product.id}/check-player",
        json={"player_id": "gaben-error"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


@respx.mock
async def test_steam_login_never_logged_plaintext(
    client: httpx.AsyncClient, seed_waxpeer_product: Product
) -> None:
    """Same PII guarantee as ``test_player_id_never_logged_plaintext``, for
    the waxpeer branch: the raw Steam login must never reach a log event,
    only its ``_hash_short`` hash. The upstream-error path is the best
    trigger here — it's the one line (``player_check_failed``) that logs the
    login-derived field via ``logger.warning`` instead of ``logger.info``,
    so this also exercises the warning call site the other steam tests
    don't."""
    respx.get(url__regex=r".*/steam-topup/validate").mock(side_effect=httpx.ConnectError("down"))
    secret = "gaben-secret-login"
    with structlog.testing.capture_logs() as cap:
        r = await client.post(
            f"/api/v1/catalog/products/{seed_waxpeer_product.id}/check-player",
            json={"player_id": secret},
        )
    assert r.status_code == 200
    assert r.json()["status"] == "error"
    log_text = " ".join(repr(entry) for entry in cap)
    assert secret not in log_text
