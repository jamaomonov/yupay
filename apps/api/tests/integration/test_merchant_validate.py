"""``POST /merchant/v1/validate/player`` — the truthful player check (M3a, Task 5).

Spec §9.1's sixth row: expose the existing player-check providers to a
reseller, **only where the answer is truthful**, and never as a fake approver.
Everything here runs against the live mounted app, so a failure is the shipped
surface's.

The three rules this file exists to pin, in the order they matter:

1. **``error`` never renders as ``valid``.** An upstream fault, a tripped
   breaker and an unconfigured supplier are all "we could not check", and a
   reseller acting on a cheerful default sells into a wrong account.
2. **A brand with no configured checker says so** — ``status="unsupported"``,
   which is neither ``valid`` nor a 404 that reads as "no such brand".
3. **Our own confidence is reported honestly.** A cached verdict is still our
   best answer and carries no caveat; nothing here invents certainty the
   upstream did not give.

**Why the faults below are 401s and 400s rather than a dropped connection.**
A network error or a read timeout is retried by ``G2bClient`` four times with
a 1→2→4→8 s backoff, so one such test costs fifteen seconds of real sleeping.
That branch is already pinned at the service level by
``test_player_check_endpoint.py::test_g2b_error_degrades_to_error_status``,
and it arrives here as the same ``UpstreamUnavailableError`` these do — so
this module buys the same coverage from the fail-fast statuses instead.

The signature is rebuilt by hand from the module README rather than imported
from ``merchants.signing`` — the same reason ``test_merchant_api_read.py``
gives: a test that calls the implementation it is testing proves only that the
function is deterministic.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest
import respx
import structlog.testing
from httpx import AsyncClient, Response
from sqlalchemy import select, update
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
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
VALIDATE_PATH = "/merchant/v1/validate/player"
G2B_BASE = "https://g2b.test/v1"
WAXPEER_BASE = "https://waxpeer.test/v1"
GAME_CODE = "pubgm-b2b"
CHECK_PLAYER_URL = r".*/games/checkPlayerId"


# ---------- supplier wiring ----------


@pytest.fixture(autouse=True)
def _supplier_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Both adapters report ``available`` only when their key is set.

    Same wiring as ``test_player_check_endpoint.py`` — without it every check
    would short-circuit to ``error`` for the boring reason and the tests below
    would pass while proving nothing.
    """
    monkeypatch.setenv("G2B_API_KEY", "test-key")
    monkeypatch.setenv("G2B_BASE_URL", G2B_BASE)
    monkeypatch.setenv("WAXPEER_API_KEY", "test-waxpeer-key")
    monkeypatch.setenv("WAXPEER_BASE_URL", WAXPEER_BASE)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


# ---------- harness ----------


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


@pytest.fixture
async def admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    """Log a Telegram user in and grant it the admin role."""
    user_json = json.dumps({"id": 95, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await integration_client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == 95)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


async def _new_merchant(client: AsyncClient, headers: dict[str, str]) -> str:
    r = await client.post("/api/v1/admin/merchants", headers=headers, json={"title": "Reseller"})
    assert r.status_code == 201, r.text
    merchant_id: str = r.json()["id"]
    return merchant_id


async def _new_key(
    client: AsyncClient, headers: dict[str, str], merchant_id: str
) -> tuple[str, str]:
    r = await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/api-keys",
        headers=headers,
        json={"label": "server"},
    )
    assert r.status_code == 201, r.text
    payload = r.json()
    return payload["key_id"], payload["secret"]


@pytest.fixture
async def credentials(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> tuple[str, str]:
    """A live merchant's ``(key_id, secret)`` — the only thing most tests need."""
    merchant_id = await _new_merchant(integration_client, admin_headers)
    return await _new_key(integration_client, admin_headers, merchant_id)


def _signed(key_id: str, secret: str, *, method: str, path: str, body: bytes) -> dict[str, str]:
    """The three auth headers, transcribed from the module README by hand."""
    ts = str(int(time.time()))
    message = "\n".join((ts, method.upper(), path, "", hashlib.sha256(body).hexdigest())).encode()
    return {
        "X-Merchant-Key": key_id,
        "X-Merchant-Timestamp": ts,
        "X-Merchant-Signature": hmac.new(
            secret.encode("utf-8"), message, hashlib.sha256
        ).hexdigest(),
        "Content-Type": "application/json",
    }


async def _validate(
    client: AsyncClient, credentials: tuple[str, str], payload: dict[str, Any]
) -> Response:
    """Sign and send exactly the bytes we send — never a re-serialised body."""
    key_id, secret = credentials
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return await client.post(
        VALIDATE_PATH,
        content=body,
        headers=_signed(key_id, secret, method="POST", path=VALIDATE_PATH, body=body),
    )


@pytest.fixture
async def sql_counter(db_engine) -> AsyncIterator[dict[str, int]]:  # type: ignore[no-untyped-def]  # conftest fixture is untyped
    """Counts every cursor execution on the engine the app is wired to.

    Same shape as ``test_merchant_api_read.py``'s, which pins the catalog's
    query count for the same reason: a fan-out is invisible until it is
    counted.
    """
    from sqlalchemy import event

    holder = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany) -> None:  # type: ignore[no-untyped-def]  # SQLAlchemy event signature
        holder["n"] += 1

    sync_engine = db_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        yield holder
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)


# ---------- catalog seeding ----------

_G2B_FIELD = [
    {"key": "player_id", "label": {"ru": "ID"}, "type": "text", "check": {"provider": "g2b"}}
]
_WAXPEER_FIELD = [
    {
        "key": "steam_login",
        "label": {"ru": "Логин"},
        "type": "text",
        "check": {"provider": "waxpeer"},
    }
]
_PLAIN_FIELD = [{"key": "email", "label": {"ru": "Почта"}, "type": "text"}]


def _tree(
    n: int,
    *,
    required_fields: list[dict[str, Any]],
    brand_visible_b2b: bool = True,
    sku_visible_b2b: bool = True,
) -> tuple[Category, Brand, Product, Sku]:
    """One category → brand → product → SKU unit, B2B-visible by default."""
    category = Category(
        id=new_id(),
        slug=f"cat-validate-{n}",
        sort_order=n,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=f"Категория {n}")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-validate-{n}",
        category_id=category.id,
        sort_order=n,
        active=True,
        visible_b2b=brand_visible_b2b,
        translations=[BrandTranslation(locale="ru", name=f"Бренд {n}")],
    )
    product = Product(
        id=new_id(),
        slug=f"product-validate-{n}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=n,
        active=True,
        required_fields=required_fields,
        translations=[ProductTranslation(locale="ru", name=f"Продукт {n}")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sku-validate-{n}",
        denomination="60",
        region="WW",
        price_usd=Decimal("1.00"),
        cost_usdt=Decimal("0.80"),
        b2b_markup_pct=Decimal("7.00"),
        visible_b2b=sku_visible_b2b,
        sort_order=n,
        active=True,
    )
    return category, brand, product, sku


@pytest.fixture
async def g2b_sku_id(db_session: AsyncSession) -> str:
    """A B2B-visible SKU whose product opts into the G2B nickname lookup."""
    category, brand, product, sku = _tree(1, required_fields=_G2B_FIELD)
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    # The mapping lands in its own commit: SQLAlchemy orders cross-table
    # INSERTs only through declared relationships, and ``Sku`` /
    # ``SkuSupplierMapping`` share only a raw FK column — one combined commit
    # can emit the mapping first and trip the constraint.
    db_session.add(
        SkuSupplierMapping(
            sku_id=sku.id,
            supplier_slug="g2b",
            kind="game",
            external_product_id=GAME_CODE,
            external_variant_id="60UC",
            is_active=True,
        )
    )
    await db_session.commit()
    return sku.id


@pytest.fixture
async def waxpeer_sku_id(db_session: AsyncSession) -> str:
    """A B2B-visible SKU whose product checks a Steam login through Waxpeer."""
    category, brand, product, sku = _tree(2, required_fields=_WAXPEER_FIELD)
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return sku.id


@pytest.fixture
async def plain_sku_id(db_session: AsyncSession) -> str:
    """A B2B-visible SKU whose product declares no ``check`` on any field."""
    category, brand, product, sku = _tree(3, required_fields=_PLAIN_FIELD)
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return sku.id


# ---------- the verdict is the upstream's ----------


@respx.mock
async def test_a_checkable_sku_returns_the_upstream_verdict(
    integration_client: AsyncClient, credentials: tuple[str, str], g2b_sku_id: str
) -> None:
    """The whole point: a real hit comes back as ``valid`` with the nickname."""
    route = respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )

    r = await _validate(
        integration_client, credentials, {"brand": "brand-validate-1", "player_id": "51234567"}
    )

    assert r.status_code == 200, r.text
    assert r.json() == {"status": "valid", "name": "Neo"}
    assert route.called


@respx.mock
async def test_an_id_the_supplier_rejects_is_invalid_not_error(
    integration_client: AsyncClient, credentials: tuple[str, str], g2b_sku_id: str
) -> None:
    """G2B answers a bad id with a 400 carrying the verdict; that is the
    customer's mistake, not a fault, and the reseller must be able to tell."""
    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(400, json={"valid": "invalid", "name": ""})
    )

    r = await _validate(
        integration_client, credentials, {"brand": "brand-validate-1", "player_id": "9"}
    )

    assert r.status_code == 200, r.text
    assert r.json() == {"status": "invalid", "name": None}


@respx.mock
async def test_a_steam_login_is_checked_through_waxpeer(
    integration_client: AsyncClient, credentials: tuple[str, str], waxpeer_sku_id: str
) -> None:
    """The second provider, reached by the same endpoint and the same field.

    Steam has no display name, so ``name`` stays ``null`` — the absence is the
    honest answer, not a placeholder.
    """
    respx.get(url__regex=r".*/steam-topup/validate").mock(
        return_value=httpx.Response(200, json={"success": True, "valid": True})
    )

    r = await _validate(
        integration_client, credentials, {"brand": "brand-validate-2", "player_id": "gaben"}
    )

    assert r.status_code == 200, r.text
    assert r.json() == {"status": "valid", "name": None}


# ---------- "we could not check" is never "valid" ----------


@respx.mock
async def test_an_upstream_fault_is_error_never_valid(
    integration_client: AsyncClient, credentials: tuple[str, str], g2b_sku_id: str
) -> None:
    """The failure this endpoint exists to prevent.

    A 400 with no verdict in it is a malformed request or an unknown game on
    G2B's side — our fault or theirs, never the player's. It must not read as
    approval, and it must not read as a bad id either.
    """
    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(400, json={"message": "bad request"})
    )

    r = await _validate(
        integration_client, credentials, {"brand": "brand-validate-1", "player_id": "51234567"}
    )

    assert r.status_code == 200, r.text
    assert r.json() == {"status": "error", "name": None}


@respx.mock
async def test_a_rejected_credential_is_error_never_valid(
    integration_client: AsyncClient, credentials: tuple[str, str], g2b_sku_id: str
) -> None:
    """Our own key being refused at G2B is the starkest "we could not check":
    nothing about the player was learned at all."""
    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(401, json={"message": "unauthorized"})
    )

    r = await _validate(
        integration_client, credentials, {"brand": "brand-validate-1", "player_id": "51234567"}
    )

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "error"


@respx.mock
async def test_a_tripped_breaker_is_error_never_valid(
    integration_client: AsyncClient, credentials: tuple[str, str], g2b_sku_id: str
) -> None:
    """An open circuit skips the call entirely — and still answers ``error``.

    The upstream is mocked *healthy* for the last request on purpose: if the
    short circuit ever leaked as ``valid``, this is where it would show,
    because the only thing standing between "we did not call" and "the id is
    good" is the status we choose. 401 is used to fill the circuit because
    ``player_check._counts_against_supplier`` counts it and it fails fast.
    """
    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(401, json={"message": "unauthorized"})
    )
    for _ in range(3):  # ``player_check._BREAKER_THRESHOLD``
        opening = await _validate(
            integration_client, credentials, {"brand": "brand-validate-1", "player_id": "51234567"}
        )
        assert opening.json()["status"] == "error", opening.text

    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    r = await _validate(
        integration_client, credentials, {"brand": "brand-validate-1", "player_id": "77777777"}
    )

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "error"


@respx.mock
async def test_a_verdict_we_cannot_read_is_error_never_invalid(
    integration_client: AsyncClient, credentials: tuple[str, str], g2b_sku_id: str
) -> None:
    """The mirror of the rule above, and the louder half of it.

    ``invalid`` is published as the one answer meaning the customer mistyped.
    So a 200 whose ``valid`` field has been renamed must **not** map to it: no
    breaker fires on a 200, nothing logs a failure, and the whole platform
    would quietly start telling every customer their id was wrong. It is
    ``error`` — we could not check.
    """
    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(200, json={"is_valid": "valid", "name": "Neo"})
    )

    r = await _validate(
        integration_client, credentials, {"brand": "brand-validate-1", "player_id": "51234567"}
    )

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "error"


@respx.mock
async def test_a_steam_verdict_we_cannot_read_is_error_never_invalid(
    integration_client: AsyncClient, credentials: tuple[str, str], waxpeer_sku_id: str
) -> None:
    """The same rule on the other provider: Waxpeer's ``valid`` gone missing."""
    respx.get(url__regex=r".*/steam-topup/validate").mock(
        return_value=httpx.Response(200, json={"success": True, "msg": "ok"})
    )

    r = await _validate(
        integration_client, credentials, {"brand": "brand-validate-2", "player_id": "gaben"}
    )

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "error"


async def test_an_unconfigured_supplier_is_error_never_valid(
    integration_client: AsyncClient,
    credentials: tuple[str, str],
    g2b_sku_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stack with no G2B key cannot check anything, and says so."""
    monkeypatch.setenv("G2B_API_KEY", "")
    cfg.get_settings.cache_clear()

    r = await _validate(
        integration_client, credentials, {"brand": "brand-validate-1", "player_id": "51234567"}
    )

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "error"


# ---------- a SKU with no checker says so ----------


async def test_a_sku_with_no_checker_is_unsupported_not_valid(
    integration_client: AsyncClient, credentials: tuple[str, str], plain_sku_id: str
) -> None:
    """Consequence 2: a distinct answer meaning "no check exists here".

    Not ``valid`` (a fake approver), and not a 404 — which reads as "no such
    SKU" and would send an integrator hunting an id that is perfectly fine.
    Not ``error`` either: one is permanent and the other is worth retrying,
    and collapsing them would have a reseller retry a SKU that will never be
    checkable.
    """
    r = await _validate(
        integration_client, credentials, {"brand": "brand-validate-3", "player_id": "51234567"}
    )

    assert r.status_code == 200, r.text
    assert r.json() == {"status": "unsupported", "name": None}


# ---------- scoping: no enumeration of what they cannot buy ----------


async def test_a_sku_id_is_no_longer_accepted(
    integration_client: AsyncClient, credentials: tuple[str, str], g2b_sku_id: str
) -> None:
    """The body is a brand now. `extra="forbid"` turns the old field into a
    422 that names it, instead of a check of nothing."""
    r = await _validate(
        integration_client, credentials, {"sku_id": g2b_sku_id, "player_id": "51234567"}
    )
    assert r.status_code == 422, r.text
    assert "brand" in r.text


async def test_an_unknown_brand_is_refused_by_name(
    integration_client: AsyncClient, credentials: tuple[str, str]
) -> None:
    r = await _validate(
        integration_client, credentials, {"brand": "no-such-brand", "player_id": "1"}
    )
    assert r.status_code == 404, r.text
    body = r.json()
    assert body["code"] == "item_unavailable"
    assert body["reason"] == "unknown_brand"
    assert body["brand"] == "no-such-brand"
    assert "sku_id" not in body


async def test_a_brand_withheld_from_b2b_is_not_checkable(
    integration_client: AsyncClient, credentials: tuple[str, str], db_session: AsyncSession
) -> None:
    category, brand, product, sku = _tree(7, required_fields=_G2B_FIELD, brand_visible_b2b=False)
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    r = await _validate(integration_client, credentials, {"brand": brand.slug, "player_id": "1"})
    assert r.status_code == 404, r.text
    body = r.json()
    assert body["reason"] == "not_b2b_visible"
    assert body["brand"] == brand.slug
    assert "sku_id" not in body


async def test_a_visible_brand_with_no_visible_sku_is_not_checkable(
    integration_client: AsyncClient, credentials: tuple[str, str], db_session: AsyncSession
) -> None:
    """The second half of the visibility rule: the brand itself is
    ``visible_b2b``, but none of its SKUs are — the correlated ``EXISTS`` in
    ``_checkable_brand`` is what catches this, distinct from the brand-level
    refusal above."""
    category, brand, product, sku = _tree(8, required_fields=_G2B_FIELD, sku_visible_b2b=False)
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    r = await _validate(integration_client, credentials, {"brand": brand.slug, "player_id": "1"})
    assert r.status_code == 404, r.text
    body = r.json()
    assert body["reason"] == "not_b2b_visible"
    assert body["brand"] == brand.slug


async def test_an_unknown_body_field_is_refused(
    integration_client: AsyncClient, credentials: tuple[str, str], g2b_sku_id: str
) -> None:
    """``extra="forbid"``: a typo'd field name must not silently check nothing."""
    r = await _validate(
        integration_client,
        credentials,
        {"brand": "brand-validate-1", "playerid": "51234567"},
    )

    assert r.status_code == 422, r.text


# ---------- the cache is our best answer, with no caveat ----------


@respx.mock
async def test_a_cached_verdict_is_returned_unchanged(
    integration_client: AsyncClient, credentials: tuple[str, str], g2b_sku_id: str
) -> None:
    """Consequence 3: a 300 s cache hit is still our best answer.

    The upstream answers once and is then broken; the second call must return
    the same body — not a downgraded one, and not a caveat field that would
    make an integrator treat a good answer as doubtful.
    """
    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    first = await _validate(
        integration_client, credentials, {"brand": "brand-validate-1", "player_id": "31313131"}
    )
    assert first.json() == {"status": "valid", "name": "Neo"}

    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(401, json={"message": "unauthorized"})
    )
    second = await _validate(
        integration_client, credentials, {"brand": "brand-validate-1", "player_id": "31313131"}
    )

    assert second.status_code == 200, second.text
    assert second.json() == first.json()


@respx.mock
async def test_an_error_is_never_cached(
    integration_client: AsyncClient, credentials: tuple[str, str], g2b_sku_id: str
) -> None:
    """The complement of the test above, and the one a refactor breaks silently.

    A cached ``error`` would outlive the outage that produced it by up to five
    minutes, so a merchant retrying after we recovered would still be told we
    could not check. It is structurally impossible today — only mapped verdicts
    reach ``redis.set`` — which is exactly why it needs an assertion rather
    than a reading of the code.
    """
    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(401, json={"message": "unauthorized"})
    )
    broken = await _validate(
        integration_client, credentials, {"brand": "brand-validate-1", "player_id": "24242424"}
    )
    assert broken.json()["status"] == "error"

    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    repaired = await _validate(
        integration_client, credentials, {"brand": "brand-validate-1", "player_id": "24242424"}
    )

    assert repaired.json() == {"status": "valid", "name": "Neo"}


@respx.mock
async def test_the_check_does_not_fan_out_over_the_catalog(
    integration_client: AsyncClient,
    credentials: tuple[str, str],
    g2b_sku_id: str,
    sql_counter: dict[str, int],
) -> None:
    """AGENTS §10: an advisory lookup must not drag the retail catalog with it.

    ``player_check`` used to re-read the product with ``session.get``, whose
    selectin relationships (translations, FAQs, the SKU set, the brand — and
    ``Brand.products`` in turn) fanned out to nine statements per call, at up
    to two calls a second. The ceiling is deliberately generous and far below
    that: what it pins is the absence of a per-relationship fan-out, not an
    exact plan.
    """
    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    before = sql_counter["n"]

    r = await _validate(
        integration_client, credentials, {"brand": "brand-validate-1", "player_id": "61616161"}
    )

    assert r.status_code == 200, r.text
    spent = sql_counter["n"] - before
    assert spent <= 6, f"{spent} statements for one check — the entity fan-out is back"


# ---------- rate limiting ----------


async def test_the_endpoint_carries_its_own_stricter_bucket() -> None:
    """Spec §12: stricter on ``validate/*`` — it spends supplier quota.

    Pinned as a relation rather than a number so a future retune cannot
    quietly make the validate ceiling the prefix ceiling, which is the whole
    reason the bucket exists.
    """
    from yupay.modules.auth.ip_guard import bucket_limit
    from yupay.modules.merchants.auth import RATE_BUCKET
    from yupay.modules.merchants.validate import RATE_BUCKET as VALIDATE_BUCKET

    settings = cfg.get_settings()
    assert VALIDATE_BUCKET != RATE_BUCKET
    assert bucket_limit(settings, VALIDATE_BUCKET) < bucket_limit(settings, RATE_BUCKET)
    # Still a machine caller's ceiling, not a person's.
    assert bucket_limit(settings, VALIDATE_BUCKET) > bucket_limit(settings, "login")


@respx.mock
async def test_the_bucket_throttles_with_a_retry_after(
    integration_client: AsyncClient,
    credentials: tuple[str, str],
    g2b_sku_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Past the ceiling: 429, problem+json, and a ``Retry-After`` a machine
    client can obey — the coarse slowapi tier does not cover this prefix."""
    monkeypatch.setenv("AUTH_IP_GUARD_BUCKET_MAX", '{"merchant-validate": 3}')
    cfg.get_settings.cache_clear()
    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )

    last: Response | None = None
    for _ in range(6):
        last = await _validate(
            integration_client, credentials, {"brand": "brand-validate-1", "player_id": "51234567"}
        )
    assert last is not None

    assert last.status_code == 429, last.text
    assert last.headers["content-type"].startswith("application/problem+json")
    assert last.headers["Retry-After"]
    cfg.get_settings.cache_clear()


@respx.mock
async def test_the_merchant_axis_throttles_across_addresses(
    integration_client: AsyncClient,
    credentials: tuple[str, str],
    g2b_sku_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The address bucket is not what bounds a merchant's supplier spend.

    A reseller on a multi-node egress pool has one IP counter per NAT address,
    so the ceiling that follows the *account* has to be its own counter. Here
    the IP bucket is set far above the merchant ceiling, which means only the
    merchant axis can produce the 429 — if it were missing, all six calls would
    answer 200.
    """
    monkeypatch.setenv("AUTH_IP_GUARD_BUCKET_MAX", '{"merchant-validate": 9999}')
    monkeypatch.setenv("MERCHANT_VALIDATE_RATE_MAX", "3")
    cfg.get_settings.cache_clear()
    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )

    last: Response | None = None
    for _ in range(6):
        last = await _validate(
            integration_client, credentials, {"brand": "brand-validate-1", "player_id": "51234567"}
        )
    assert last is not None

    assert last.status_code == 429, last.text
    assert last.headers["Retry-After"]
    assert last.headers["content-type"].startswith("application/problem+json")
    cfg.get_settings.cache_clear()


@respx.mock
async def test_one_merchants_checks_do_not_spend_anothers_quota(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    g2b_sku_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The counter follows the account, so it must not be shared between them."""
    monkeypatch.setenv("AUTH_IP_GUARD_BUCKET_MAX", '{"merchant-validate": 9999}')
    monkeypatch.setenv("MERCHANT_VALIDATE_RATE_MAX", "2")
    cfg.get_settings.cache_clear()
    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    noisy = await _new_key(
        integration_client, admin_headers, await _new_merchant(integration_client, admin_headers)
    )
    quiet = await _new_key(
        integration_client, admin_headers, await _new_merchant(integration_client, admin_headers)
    )
    for _ in range(4):
        await _validate(
            integration_client, noisy, {"brand": "brand-validate-1", "player_id": "51234567"}
        )

    r = await _validate(
        integration_client, quiet, {"brand": "brand-validate-1", "player_id": "51234567"}
    )

    assert r.status_code == 200, r.text
    cfg.get_settings.cache_clear()


# ---------- auth, and the identifier that must not be logged ----------


async def test_an_unsigned_request_is_refused(integration_client: AsyncClient) -> None:
    r = await integration_client.post(VALIDATE_PATH, json={})

    assert r.status_code == 401, r.text
    assert r.json()["code"] == "missing_credentials"


async def test_a_frozen_merchant_is_refused(
    integration_client: AsyncClient, admin_headers: dict[str, str], g2b_sku_id: str
) -> None:
    merchant_id = await _new_merchant(integration_client, admin_headers)
    key_id, secret = await _new_key(integration_client, admin_headers, merchant_id)
    frozen = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/freeze", headers=admin_headers
    )
    assert frozen.status_code == 200, frozen.text

    r = await _validate(
        integration_client, (key_id, secret), {"brand": "brand-validate-1", "player_id": "1"}
    )

    assert r.status_code == 403, r.text
    assert r.json()["code"] == "merchant_frozen"


@respx.mock
async def test_the_players_identifier_is_never_logged(
    integration_client: AsyncClient, credentials: tuple[str, str], g2b_sku_id: str
) -> None:
    """Ruling 3 / AGENTS §9: the id belongs to the reseller's end customer and
    is transit-only. ``structlog.testing.capture_logs`` rather than ``caplog``
    — ``configure_logging`` wires a print factory that never reaches stdlib
    logging, so ``caplog.text`` is vacuously empty."""
    respx.post(url__regex=CHECK_PLAYER_URL).mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    secret_id = "84218421"

    with structlog.testing.capture_logs() as captured:
        r = await _validate(
            integration_client, credentials, {"brand": "brand-validate-1", "player_id": secret_id}
        )

    assert r.status_code == 200, r.text
    assert secret_id not in " ".join(repr(entry) for entry in captured)
