# Storefront player-id check (G2B nickname lookup) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a storefront customer type their game player id, tap "Проверить", and see the nickname G2B resolves it to — advisory, never gating checkout.

**Architecture:** A `check` descriptor on the form field opts a product in. A public endpoint in the `integrations` module resolves the product's G2B `game_code` from its supplier mapping, calls the existing `games_check_player`, caches the result in Redis, and returns `{valid, name, reason}`. The miniapp and web form renderers show a check button wired to that endpoint. Fulfilment is untouched.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 async / Pydantic v2 / slowapi / Redis; TypeScript / React (miniapp Vite, web Next.js); pytest + respx; Vitest.

## Global Constraints

- **Advisory only** — the check never blocks order creation. A G2B outage or a game with no checker must still allow purchase.
- **PII (§9)** — `player_id` is NEVER logged in plaintext. Use `_hash_short` from the G2B module. `player_id`/nickname are not persisted by this feature.
- **Rate limit (§9)** — the public endpoint is per-IP guarded (reuse `guard_ip`, new bucket `check_player`).
- **§10 deviation** — one synchronous external HTTP call in the handler, deliberately (advisory, user-initiated, short-timeout, cached). Documented in a new ADR.
- **i18n** — every new user-facing string added to `ru`, `en`, `uz` in the same change; never hardcode (`t("namespace.key")`).
- **Money/types** — n/a here (no money handling).
- **Line length** Python 100; **mypy --strict**, no `any`/`Any` without justification; TS `strict`, no `any`.
- **OpenAPI drift** — after backend routes/schemas change, run `make gen-api` and commit the regenerated `docs/api/openapi.json` + `packages/api-client`.

---

## File structure

**Backend (`apps/api/src/yupay`):**

- `modules/catalog/schemas.py` — MODIFY: add `FieldCheck` submodel + `FormField.check`.
- `modules/integrations/player_check.py` — CREATE: game_code resolver + `check_player_for_product` service + Redis cache.
- `modules/integrations/schemas.py` — MODIFY: add public `PlayerCheckIn` / `PlayerCheckOut`.
- `modules/integrations/routes.py` — MODIFY: add public `router` with the POST route + `guard_ip`.
- `modules/integrations/api.py` — MODIFY: export `router`, `PlayerCheckIn`, `PlayerCheckOut`, `check_player_for_product`.
- `api/v1/__init__.py` — MODIFY: mount the public integrations router.
- `scripts/seed_catalog.py` — MODIFY: `_player_id_field(check=...)`; PUBG et al. seed the descriptor.

**Frontend miniapp (`apps/miniapp/src`):**

- `lib/catalog.ts` — MODIFY: extend `FormField` with `check`.
- `lib/player-check.ts` — CREATE: `checkPlayer()` API wrapper.
- `components/DynamicFields.tsx` — MODIFY: render the check button + states.

**Frontend web (`apps/web/src`):**

- `lib/catalog.ts` — MODIFY: extend `FormField`.
- `lib/player-check.ts` — CREATE: `checkPlayer()` wrapper.
- `components/store/PurchasePanel.tsx` — MODIFY: render the check button + states.

**i18n (`packages/i18n/locales/{ru,en,uz}`):** MODIFY the relevant namespace json.

**Docs:** `docs/decisions/0031-storefront-player-check.md` (CREATE), `modules/catalog/README.md` (MODIFY), `docs/architecture/cache-keys.md` (MODIFY).

**Tests:**

- `apps/api/tests/unit/test_form_field_check_schema.py` (CREATE)
- `apps/api/tests/unit/test_player_check_service.py` (CREATE)
- `apps/api/tests/integration/test_player_check_endpoint.py` (CREATE)
- `apps/miniapp/src/components/DynamicFields.test.tsx` (CREATE)
- `apps/web/src/components/store/PurchasePanel.test.tsx` (CREATE or extend)

---

## Task 1: `FieldCheck` descriptor on `FormField`

**Files:**

- Modify: `apps/api/src/yupay/modules/catalog/schemas.py` (FormField block, ~lines 18-40)
- Test: `apps/api/tests/unit/test_form_field_check_schema.py`

**Interfaces:**

- Produces: `FieldCheck(BaseModel){ provider: Literal["g2b"]; server_field: str | None = None }`; `FormField.check: FieldCheck | None = None`.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/unit/test_form_field_check_schema.py
"""FormField.check descriptor parsing (storefront player-check opt-in)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from yupay.modules.catalog.schemas import FieldCheck, FormField


def _base_field(**extra: object) -> dict[str, object]:
    return {"key": "player_id", "label": {"ru": "ID"}, "type": "text", **extra}


def test_field_without_check_defaults_to_none() -> None:
    field = FormField.model_validate(_base_field())
    assert field.check is None


def test_field_with_g2b_check_parses() -> None:
    field = FormField.model_validate(
        _base_field(check={"provider": "g2b", "server_field": "server"})
    )
    assert field.check == FieldCheck(provider="g2b", server_field="server")


def test_check_server_field_is_optional() -> None:
    field = FormField.model_validate(_base_field(check={"provider": "g2b"}))
    assert field.check is not None
    assert field.check.server_field is None


def test_unknown_provider_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        FormField.model_validate(_base_field(check={"provider": "nope"}))


def test_extra_key_in_check_forbidden() -> None:
    with pytest.raises(PydanticValidationError):
        FormField.model_validate(_base_field(check={"provider": "g2b", "wat": 1}))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && uv run pytest tests/unit/test_form_field_check_schema.py -q`
Expected: FAIL — `ImportError: cannot import name 'FieldCheck'`.

- [ ] **Step 3: Implement the schema**

In `apps/api/src/yupay/modules/catalog/schemas.py`, add `FieldCheck` immediately before `class FormField` and the `check` field inside `FormField` (after `options`):

```python
class FieldCheck(BaseModel):
    """Opts a form field into storefront player verification.

    Present only on the player-id field. ``server_field`` names the sibling
    field whose value is passed as the checker's ``server_id`` (games like
    Mobile Legends need a zone; PUBG Mobile does not).
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["g2b"]
    server_field: str | None = None


class FormField(BaseModel):
    """One field of a product's form schema."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: LocaleMap
    type: Literal["text", "email", "number", "select"]
    required: bool = True
    placeholder: LocaleMap | None = None
    help_text: LocaleMap | None = None
    pattern: str | None = None
    options: list[FormOption] | None = None
    check: FieldCheck | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && uv run pytest tests/unit/test_form_field_check_schema.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint + typecheck the touched files**

Run: `cd apps/api && uv run ruff check src/yupay/modules/catalog/schemas.py tests/unit/test_form_field_check_schema.py && uv run mypy src/yupay/modules/catalog/schemas.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/catalog/schemas.py apps/api/tests/unit/test_form_field_check_schema.py
git commit -m "feat(api/catalog): FieldCheck descriptor on FormField"
```

---

## Task 2: Public request/response schemas

**Files:**

- Modify: `apps/api/src/yupay/modules/integrations/schemas.py` (near `CheckPlayerIn`, ~line 172), and the `__all__` list.
- Test: covered by Task 3/5 (pure DTOs — no standalone test needed).

**Interfaces:**

- Produces: `PlayerCheckIn(BaseModel){ player_id: str; server_id: str | None = None }` (extra forbid, `player_id` 1-64 chars); `PlayerCheckOut(BaseModel){ valid: bool; name: str | None = None; reason: str | None = None }`.

- [ ] **Step 1: Add the schemas**

In `apps/api/src/yupay/modules/integrations/schemas.py`, after the existing `CheckPlayerOut` class:

```python
class PlayerCheckIn(BaseModel):
    """Storefront player-verification request (no charname — it's a lookup)."""

    model_config = ConfigDict(extra="forbid")

    player_id: str = Field(min_length=1, max_length=64)
    server_id: str | None = Field(default=None, max_length=64)


class PlayerCheckOut(BaseModel):
    """Storefront player-verification result. ``openid`` is intentionally
    omitted — it's an internal G2B id and must not leak to the storefront."""

    valid: bool
    name: str | None = None
    reason: str | None = None
```

Add `"PlayerCheckIn",` and `"PlayerCheckOut",` to the module's `__all__` (keep alphabetical grouping consistent with neighbours).

- [ ] **Step 2: Typecheck**

Run: `cd apps/api && uv run ruff check src/yupay/modules/integrations/schemas.py && uv run mypy src/yupay/modules/integrations/schemas.py`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/api/src/yupay/modules/integrations/schemas.py
git commit -m "feat(api/integrations): public PlayerCheckIn/PlayerCheckOut schemas"
```

---

## Task 3: `check_player_for_product` service + game_code resolver + cache

**Files:**

- Create: `apps/api/src/yupay/modules/integrations/player_check.py`
- Test: `apps/api/tests/unit/test_player_check_service.py`

**Interfaces:**

- Consumes: `PlayerCheckOut` (Task 2); `FormField`/`FieldCheck` (Task 1); `_g2b_fulfiller_or_none` (move to this module — see Step 3); `_hash_short` from `yupay.modules.fulfillment.suppliers.g2b`; `get_redis` from `yupay.core.redis`.
- Produces:
  - `product_is_checkable(required_fields: list[dict]) -> bool`
  - `async resolve_g2b_game_code(session, product_id: str) -> str | None`
  - `async check_player_for_product(session, *, product_id: str, player_id: str, server_id: str | None) -> PlayerCheckOut`
  - Raises `NotFoundError` when the product does not exist, `ValidationError` when it exists but is not checkable.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/unit/test_player_check_service.py
"""check_player_for_product: mapping resolution, response shaping, cache, PII."""

from __future__ import annotations

import pytest

from yupay.modules.integrations import player_check as pc


def test_product_is_checkable_true_when_field_has_g2b_check() -> None:
    fields = [{"key": "player_id", "label": {"ru": "ID"}, "type": "text",
               "check": {"provider": "g2b"}}]
    assert pc.product_is_checkable(fields) is True


def test_product_is_checkable_false_without_check() -> None:
    fields = [{"key": "player_id", "label": {"ru": "ID"}, "type": "text"}]
    assert pc.product_is_checkable(fields) is False


def test_map_g2b_response_valid() -> None:
    out = pc._map_response({"valid": "valid", "name": "Neo", "openid": "x"})
    assert out.valid is True
    assert out.name == "Neo"
    assert out.reason is None


def test_map_g2b_response_invalid() -> None:
    out = pc._map_response({"valid": "invalid", "message": "not found"})
    assert out.valid is False
    assert out.name is None
    assert out.reason == "not found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && uv run pytest tests/unit/test_player_check_service.py -q`
Expected: FAIL — module `player_check` does not exist.

- [ ] **Step 3: Implement the service**

Create `apps/api/src/yupay/modules/integrations/player_check.py`:

```python
"""Storefront player-id verification (G2B nickname lookup).

Advisory: resolves a product's G2B ``game_code`` from its supplier mapping and
proxies ``games_check_player``. Errors are folded into ``{valid: False, reason}``
so the storefront never hits an error boundary. See ADR-0031.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.catalog.models import Product, Sku
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.schemas import PlayerCheckOut

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("yupay.integrations.player_check")

_CACHE_TTL_SECONDS = 300


def product_is_checkable(required_fields: list[dict[str, Any]]) -> bool:
    """True when any form field opts into a g2b player check."""
    return any(
        isinstance(f, dict) and isinstance(f.get("check"), dict)
        and f["check"].get("provider") == "g2b"
        for f in required_fields
    )


def _map_response(resp: dict[str, Any]) -> PlayerCheckOut:
    raw_valid = str(resp.get("valid") or "").lower()
    if raw_valid == "valid":
        return PlayerCheckOut(valid=True, name=str(resp["name"]) if resp.get("name") else None)
    return PlayerCheckOut(valid=False, reason=str(resp.get("message") or "rejected"))


async def resolve_g2b_game_code(session: AsyncSession, product_id: str) -> str | None:
    """The G2B game_code for a product = external_product_id of any active
    g2b game mapping among its SKUs. A product's game SKUs share one code."""
    stmt = (
        select(SkuSupplierMapping.external_product_id)
        .join(Sku, Sku.id == SkuSupplierMapping.sku_id)
        .where(
            Sku.product_id == product_id,
            SkuSupplierMapping.supplier_slug == "g2b",
            SkuSupplierMapping.kind == "game",
            SkuSupplierMapping.is_active.is_(True),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _cache_key(game_code: str, player_id: str, server_id: str | None) -> str:
    return f"playercheck:g2b:{game_code}:{server_id or '-'}:{player_id}"


async def check_player_for_product(
    session: AsyncSession,
    *,
    product_id: str,
    player_id: str,
    server_id: str | None,
) -> PlayerCheckOut:
    """Verify a player id for a product. Never raises on upstream failure —
    folds it into ``{valid: False, reason}``."""
    from yupay.modules.fulfillment.suppliers.g2b import _hash_short
    from yupay.modules.integrations.routes import _g2b_fulfiller_or_none

    product = await session.get(Product, product_id)
    if product is None:
        raise NotFoundError("product not found")
    if not product_is_checkable(list(product.required_fields or [])):
        raise ValidationError("product is not checkable")

    game_code = await resolve_g2b_game_code(session, product_id)
    if game_code is None:
        return PlayerCheckOut(valid=False, reason="unavailable")

    redis = get_redis()
    key = _cache_key(game_code, player_id, server_id)
    try:
        cached = await redis.get(key)
    except Exception:  # noqa: BLE001 — cache is best-effort
        cached = None
    if cached:
        return PlayerCheckOut.model_validate_json(cached)

    fulfiller = _g2b_fulfiller_or_none()
    if fulfiller is None:
        return PlayerCheckOut(valid=False, reason="unavailable")

    try:
        resp = await fulfiller._client().games_check_player(
            game_code=game_code, player_id=player_id, server_id=server_id, charname=None
        )
    except Exception as exc:  # noqa: BLE001 — advisory; degrade, never 500
        logger.warning(
            "player_check_failed",
            game_code=game_code,
            player_id_hash=_hash_short(player_id),
            error=str(exc)[:200],
        )
        return PlayerCheckOut(valid=False, reason="unavailable")

    out = _map_response(resp)
    try:
        await redis.set(key, out.model_dump_json(), ex=_CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        pass
    logger.info(
        "player_check", game_code=game_code, player_id_hash=_hash_short(player_id),
        valid=out.valid,
    )
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/api && uv run pytest tests/unit/test_player_check_service.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint + typecheck**

Run: `cd apps/api && uv run ruff check src/yupay/modules/integrations/player_check.py && uv run mypy src/yupay/modules/integrations/player_check.py`
Expected: no errors. (Fix the unused `import json` if ruff flags it.)

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/integrations/player_check.py apps/api/tests/unit/test_player_check_service.py
git commit -m "feat(api/integrations): player-check service, game_code resolver, Redis cache"
```

---

## Task 4: Public endpoint + rate guard + router mount

**Files:**

- Modify: `apps/api/src/yupay/modules/integrations/routes.py` (add public `router`)
- Modify: `apps/api/src/yupay/modules/integrations/api.py` (export `router`, schemas, service fn)
- Modify: `apps/api/src/yupay/api/v1/__init__.py` (mount)
- Test: `apps/api/tests/integration/test_player_check_endpoint.py`

**Interfaces:**

- Consumes: `check_player_for_product` (Task 3); `PlayerCheckIn`/`PlayerCheckOut` (Task 2); `guard_ip` from `yupay.modules.auth.ip_guard`; `db_session` dep.
- Produces: `router` (public `APIRouter`, prefix `/catalog`) with `POST /products/{product_id}/check-player`.

- [ ] **Step 1: Write the failing integration test**

```python
# apps/api/tests/integration/test_player_check_endpoint.py
"""POST /catalog/products/{id}/check-player — storefront player verification."""

from __future__ import annotations

import httpx
import pytest
import respx

# NOTE: reuse the suite's fixtures. `client` is the ASGI httpx client;
# `seed_g2b_product` must create a Product with a checkable player_id field
# and a SKU with an active g2b game mapping (external_product_id="pubgm").
# Follow the existing pattern in tests/integration/test_integrations_g2b_game_endpoints.py
# for wiring the G2B fulfiller + respx base URL.

pytestmark = pytest.mark.integration


@respx.mock
async def test_check_player_valid(client: httpx.AsyncClient, seed_g2b_product) -> None:
    respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    r = await client.post(
        f"/api/v1/catalog/products/{seed_g2b_product.id}/check-player",
        json={"player_id": "51234567", "server_id": None},
    )
    assert r.status_code == 200
    assert r.json() == {"valid": True, "name": "Neo", "reason": None}


@respx.mock
async def test_check_player_invalid(client: httpx.AsyncClient, seed_g2b_product) -> None:
    respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "invalid", "message": "not found"})
    )
    r = await client.post(
        f"/api/v1/catalog/products/{seed_g2b_product.id}/check-player",
        json={"player_id": "9"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False and body["name"] is None


@respx.mock
async def test_g2b_error_degrades_to_unavailable(client, seed_g2b_product) -> None:
    respx.post(url__regex=r".*/games/checkPlayerId").mock(side_effect=httpx.ConnectError("down"))
    r = await client.post(
        f"/api/v1/catalog/products/{seed_g2b_product.id}/check-player",
        json={"player_id": "51234567"},
    )
    assert r.status_code == 200
    assert r.json()["valid"] is False


async def test_not_checkable_product_400(client, seed_plain_product) -> None:
    r = await client.post(
        f"/api/v1/catalog/products/{seed_plain_product.id}/check-player",
        json={"player_id": "1"},
    )
    assert r.status_code == 400


async def test_unknown_product_404(client) -> None:
    r = await client.post(
        "/api/v1/catalog/products/00000000-0000-0000-0000-000000000000/check-player",
        json={"player_id": "1"},
    )
    assert r.status_code == 404
```

Add the two fixtures (`seed_g2b_product`, `seed_plain_product`) to the test module, modelled on the seeding in `tests/integration/test_integrations_g2b_game_endpoints.py`. `seed_g2b_product` inserts a `Product` with
`required_fields=[{"key":"player_id","label":{"ru":"ID"},"type":"text","check":{"provider":"g2b"}}]`,
one `Sku`, and a `SkuSupplierMapping(supplier_slug="g2b", kind="game", external_product_id="pubgm", external_variant_id="60UC", is_active=True)`. `seed_plain_product` inserts a Product whose `required_fields` has no `check`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_player_check_endpoint.py -q`
Expected: FAIL — route 404 (not mounted yet).

- [ ] **Step 3: Add the public router**

In `apps/api/src/yupay/modules/integrations/routes.py`, add near the top imports:

```python
from fastapi import Request
from yupay.modules.auth.ip_guard import guard_ip
from yupay.modules.integrations.player_check import check_player_for_product
from yupay.modules.integrations.schemas import PlayerCheckIn, PlayerCheckOut
```

After the `admin_router = APIRouter(...)` definition, add a public router and the route:

```python
router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.post(
    "/products/{product_id}/check-player",
    response_model=PlayerCheckOut,
    summary="Verify a player id for a product (advisory nickname lookup)",
)
async def check_player(
    product_id: str,
    body: PlayerCheckIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> PlayerCheckOut:
    """Storefront-facing. Advisory — folds upstream errors into
    ``{valid: false}``; never blocks checkout. Rate-limited per IP. See ADR-0031.
    """
    await guard_ip(request, bucket="check_player")
    return await check_player_for_product(
        db, product_id=product_id, player_id=body.player_id, server_id=body.server_id
    )
```

- [ ] **Step 4: Export + mount**

In `apps/api/src/yupay/modules/integrations/api.py`: import `router` from `routes`, `PlayerCheckIn`/`PlayerCheckOut` from `schemas`, `check_player_for_product` from `player_check`; add all four to `__all__`.

In `apps/api/src/yupay/api/v1/__init__.py`: add the import (alphabetical, next to the admin one)
`from yupay.modules.integrations.api import router as integrations_router`
and, in the mount block, `router.include_router(integrations_router)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/api && uv run pytest tests/integration/test_player_check_endpoint.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Lint + typecheck**

Run: `cd apps/api && uv run ruff check src/yupay/modules/integrations tests/integration/test_player_check_endpoint.py && uv run mypy src/yupay/modules/integrations`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/yupay/modules/integrations/routes.py apps/api/src/yupay/modules/integrations/api.py apps/api/src/yupay/api/v1/__init__.py apps/api/tests/integration/test_player_check_endpoint.py
git commit -m "feat(api/integrations): public check-player endpoint with per-IP guard"
```

---

## Task 5: Rate-limit + PII regression tests

**Files:**

- Modify: `apps/api/tests/integration/test_player_check_endpoint.py`

**Interfaces:**

- Consumes: the endpoint from Task 4; `auth_ip_guard_max` setting (default 10/window).

- [ ] **Step 1: Add the rate-limit test**

```python
@respx.mock
async def test_rate_limited_after_threshold(client, seed_g2b_product) -> None:
    respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    url = f"/api/v1/catalog/products/{seed_g2b_product.id}/check-player"
    last = None
    for _ in range(15):  # window max defaults to 10
        last = await client.post(url, json={"player_id": "51234567"})
    assert last is not None and last.status_code == 429
```

Note: the `ip_guard` uses Redis. If the integration suite already provides a real/fake Redis (it does for auth ip_guard tests), this works as-is; otherwise reuse that suite's Redis fixture.

- [ ] **Step 2: Add the PII test**

```python
@respx.mock
async def test_player_id_never_logged_plaintext(client, seed_g2b_product, caplog) -> None:
    respx.post(url__regex=r".*/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "Neo"})
    )
    secret = "51234567"
    await client.post(
        f"/api/v1/catalog/products/{seed_g2b_product.id}/check-player",
        json={"player_id": secret},
    )
    assert secret not in caplog.text
```

- [ ] **Step 3: Run to verify pass**

Run: `cd apps/api && uv run pytest tests/integration/test_player_check_endpoint.py -q`
Expected: PASS (7 passed).

- [ ] **Step 4: Commit**

```bash
git add apps/api/tests/integration/test_player_check_endpoint.py
git commit -m "test(api/integrations): rate-limit + PII coverage for check-player"
```

---

## Task 6: Seed the descriptor for game products

**Files:**

- Modify: `apps/api/src/yupay/scripts/seed_catalog.py` (`_player_id_field`, ~line 82; PUBG product spec, ~line 206)

**Interfaces:**

- Consumes: `FieldCheck` shape (Task 1).

- [ ] **Step 1: Add `check` support to the field helper**

Change `_player_id_field` to accept an optional check config and emit it:

```python
def _player_id_field(
    *, label_ru: str = "ID игрока", check: dict[str, Any] | None = None
) -> dict[str, Any]:
    field: dict[str, Any] = {
        "key": "player_id",
        # ... existing keys unchanged ...
    }
    if check is not None:
        field["check"] = check
    return field
```

For the PUBG Mobile product spec (and any other G2B game product that has a game mapping in the seed), pass `check={"provider": "g2b"}` (add `"server_field": "server"` for products that also seed a `server` select field):

```python
_player_id_field(check={"provider": "g2b"}),
```

- [ ] **Step 2: Verify the seed still parses to valid FormFields**

Run: `cd apps/api && uv run python -c "from yupay.modules.catalog.schemas import FormField; from yupay.scripts.seed_catalog import _player_id_field; FormField.model_validate(_player_id_field(check={'provider':'g2b'}))"`
Expected: no output, exit 0 (validates cleanly).

- [ ] **Step 3: Lint**

Run: `cd apps/api && uv run ruff check src/yupay/scripts/seed_catalog.py`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/api/src/yupay/scripts/seed_catalog.py
git commit -m "feat(api/seed): opt PUBG player_id field into g2b player-check"
```

---

## Task 7: Regenerate the API client + OpenAPI

**Files:**

- Modify (generated): `docs/api/openapi.json`, `packages/api-client/**`

- [ ] **Step 1: Regenerate**

Run: `make gen-api`
Expected: `docs/api/openapi.json` now contains the `/catalog/products/{product_id}/check-player` path and `PlayerCheckIn`/`PlayerCheckOut`/`FieldCheck` schemas; `packages/api-client` types updated.

- [ ] **Step 2: Sanity-check drift is intentional**

Run: `git status --short packages/api-client docs/api/openapi.json`
Expected: only the new path/schemas changed — no unrelated churn.

- [ ] **Step 3: Commit**

```bash
git add docs/api/openapi.json packages/api-client
git commit -m "chore(api-client): regenerate for check-player endpoint"
```

---

## Task 8: miniapp — FormField type + API wrapper

**Files:**

- Modify: `apps/miniapp/src/lib/catalog.ts` (FormField, ~line 86)
- Create: `apps/miniapp/src/lib/player-check.ts`

**Interfaces:**

- Consumes: `apiPost` from `@/lib/api`.
- Produces: `FieldCheck` type; `FormField.check?`; `async checkPlayer(productId: string, input: { playerId: string; serverId?: string | null }): Promise<PlayerCheckResult>` where `PlayerCheckResult = { valid: boolean; name: string | null; reason: string | null }`.

- [ ] **Step 1: Extend the FormField type**

In `apps/miniapp/src/lib/catalog.ts`, add above `FormField` and a field inside it:

```ts
export interface FieldCheck {
  provider: "g2b";
  server_field?: string | null;
}

export interface FormField {
  key: string;
  label: Record<string, string>;
  type: "text" | "email" | "number" | "select";
  required: boolean;
  placeholder?: Record<string, string> | null;
  help_text?: Record<string, string> | null;
  pattern?: string | null;
  options?: FormOption[] | null;
  check?: FieldCheck | null;
}
```

- [ ] **Step 2: Add the API wrapper**

Create `apps/miniapp/src/lib/player-check.ts`:

```ts
/** Storefront player-id verification (advisory nickname lookup). */
import { apiPost } from "@/lib/api";

export interface PlayerCheckResult {
  valid: boolean;
  name: string | null;
  reason: string | null;
}

export function checkPlayer(
  productId: string,
  input: { playerId: string; serverId?: string | null },
): Promise<PlayerCheckResult> {
  return apiPost<PlayerCheckResult>(
    `/api/v1/catalog/products/${productId}/check-player`,
    { player_id: input.playerId, server_id: input.serverId ?? null },
    { anonymous: true },
  );
}
```

(Confirm the `apiPost` signature at `apps/miniapp/src/lib/api.ts:160` — `apiPost<T>(path, body, opts?)` with an `anonymous` option, as used by `loginWithTelegramInitData`.)

- [ ] **Step 3: Typecheck**

Run: `cd apps/miniapp && pnpm exec tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/miniapp/src/lib/catalog.ts apps/miniapp/src/lib/player-check.ts
git commit -m "feat(miniapp): FormField.check type + checkPlayer API wrapper"
```

---

## Task 9: miniapp — check button + states + i18n

> **AMENDED 2026-07-16 (testing approach).** The repo has no `@testing-library/react`/`jsdom`
> and vitest runs in the `node` environment (only pure-logic tests exist, e.g.
> `messages.test.ts`). Per the user's decision, do NOT introduce component-test infra. Instead
> extract the check state + orchestration into a framework-agnostic unit
> `apps/miniapp/src/lib/player-check-state.ts` and unit-test THAT in the node env; the
> `DynamicFields.tsx` button is thin glue over the unit, covered by `tsc` + a real run. The
> steps below supersede the original component-test steps.

**Files:**

- Create: `apps/miniapp/src/lib/player-check-state.ts` (pure state/orchestration unit)
- Test: `apps/miniapp/src/lib/player-check-state.test.ts` (node env)
- Modify: `apps/miniapp/src/components/DynamicFields.tsx`, `apps/miniapp/src/pages/TopUp.tsx`
- Modify: `packages/i18n/locales/{ru,en,uz}/miniapp.json`

**Original files (superseded test file removed):**

- Modify: `apps/miniapp/src/components/DynamicFields.tsx`
- Modify: `packages/i18n/locales/{ru,en,uz}/<miniapp-namespace>.json`
- Create: `apps/miniapp/src/components/DynamicFields.test.tsx`

**Interfaces:**

- Consumes: `checkPlayer`, `PlayerCheckResult` (Task 8); `useT` from `@/lib/i18n`.

Design of the change: `DynamicFields` currently receives `fields/values/onChange`. To call the endpoint it needs the `productId` and the sibling server value. Add two props: `productId: string` and keep using `values` (the server value is read from `values[field.check.server_field]`). The check button + result render inside `TextLikeField` when `field.check` is present.

- [ ] **Step 1: Add i18n keys (all three locales)**

Add to the miniapp namespace catalog (same file that already holds `field.whereToFind`, `field.clear`, etc.). Values:

```jsonc
// ru
"field.check": "Проверить",
"field.checking": "Проверяем…",
"field.checkNickname": "Ник: {name}",
"field.checkFailed": "Не удалось проверить",
// en
"field.check": "Check",
"field.checking": "Checking…",
"field.checkNickname": "Nickname: {name}",
"field.checkFailed": "Could not verify",
// uz
"field.check": "Tekshirish",
"field.checking": "Tekshirilmoqda…",
"field.checkNickname": "Nik: {name}",
"field.checkFailed": "Tekshirib boʻlmadi",
```

- [ ] **Step 2: Write the failing component test**

```tsx
// apps/miniapp/src/components/DynamicFields.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { DynamicFields } from "./DynamicFields";

vi.mock("@/lib/player-check", () => ({
  checkPlayer: vi.fn(),
}));
import { checkPlayer } from "@/lib/player-check";

const field = {
  key: "player_id",
  label: { ru: "ID" },
  type: "text" as const,
  required: true,
  check: { provider: "g2b" as const },
};

beforeEach(() => {
  vi.mocked(checkPlayer).mockReset();
});

test("shows nickname after a successful check", async () => {
  vi.mocked(checkPlayer).mockResolvedValue({ valid: true, name: "Neo", reason: null });
  render(
    <DynamicFields
      productId="p1"
      fields={[field]}
      values={{ player_id: "51234567" }}
      onChange={() => {}}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /Проверить|Check/i }));
  await waitFor(() => expect(screen.getByText(/Neo/)).toBeInTheDocument());
});

test("shows a soft failure without throwing", async () => {
  vi.mocked(checkPlayer).mockResolvedValue({ valid: false, name: null, reason: "not found" });
  render(
    <DynamicFields
      productId="p1"
      fields={[field]}
      values={{ player_id: "9" }}
      onChange={() => {}}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /Проверить|Check/i }));
  await waitFor(() => expect(screen.getByText(/Не удалось|Could not/i)).toBeInTheDocument());
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd apps/miniapp && pnpm exec vitest run src/components/DynamicFields.test.tsx`
Expected: FAIL — `productId` prop unknown / no check button rendered.

- [ ] **Step 4: Implement the button + states**

In `DynamicFields.tsx`: add `productId: string` to `DynamicFieldsProps`, thread it to `DynamicField` → `TextLikeField`. In `TextLikeField`, when `field.check` is present, render below the input a check button and result. Use local state:

```tsx
// inside TextLikeField, when field.check is set
const { check } = field;
const [state, setState] = useState<
  { phase: "idle" } | { phase: "loading" } | { phase: "done"; res: PlayerCheckResult }
>({ phase: "idle" });

// reset on value change
useEffect(() => setState({ phase: "idle" }), [value]);

async function runCheck() {
  setState({ phase: "loading" });
  try {
    const serverId = check?.server_field ? (allValues[check.server_field] ?? null) : null;
    const res = await checkPlayer(productId, { playerId: value, serverId });
    setState({ phase: "done", res });
  } catch {
    setState({ phase: "done", res: { valid: false, name: null, reason: null } });
  }
}
```

Render: a "Проверить" button disabled when `value` is empty or (if `field.pattern`) doesn't match; while `loading` show `t("field.checking")`; when `done` && `res.valid` show `t("field.checkNickname", { name: res.name })` in the primary/green style; else `t("field.checkFailed")` muted. Requires passing the full `values` map (`allValues`) into `TextLikeField` for the server field lookup — thread it through like `productId`.

Keep the button reachable by keyboard and give it an accessible name (`aria-label` = the localized "Check"). No `any`; type the result as `PlayerCheckResult`.

- [ ] **Step 5: Update `TopUp.tsx` caller**

`DynamicFields` now requires `productId`. In `apps/miniapp/src/pages/TopUp.tsx` (the `<DynamicFields ...>` usage ~line 672) pass `productId={selectedProduct.id}` (use whatever the selected product variable is named in that scope).

- [ ] **Step 6: Run tests + typecheck**

Run: `cd apps/miniapp && pnpm exec vitest run src/components/DynamicFields.test.tsx && pnpm exec tsc --noEmit`
Expected: PASS + no type errors.

- [ ] **Step 7: Commit**

```bash
git add apps/miniapp/src/components/DynamicFields.tsx apps/miniapp/src/components/DynamicFields.test.tsx apps/miniapp/src/pages/TopUp.tsx packages/i18n/locales
git commit -m "feat(miniapp): player-check button in the top-up form"
```

---

## Task 10: web — check button + states + i18n

> **AMENDED 2026-07-16 (testing approach).** Same as Task 9: no component-test infra in the web
> app either. Reuse the framework-agnostic unit from Task 9 (`player-check-state.ts`) if the web
> app can import it, or create the web equivalent `apps/web/src/lib/player-check-state.ts` with a
> node test; the `PurchasePanel.tsx` button is thin glue covered by `tsc` + a real run. No
> `PurchasePanel.test.tsx` with testing-library.

**Files:**

- Modify: `apps/web/src/lib/catalog.ts` (FormField type)
- Create: `apps/web/src/lib/player-check.ts`
- Modify: `apps/web/src/components/store/PurchasePanel.tsx` (fields render, ~line 317)
- Modify: `packages/i18n/locales/{ru,en,uz}/<web-namespace>.json` (reuse the same keys if the web store namespace differs)
- Create/Modify: `apps/web/src/components/store/PurchasePanel.test.tsx`

**Interfaces:**

- Mirrors Task 8/9 for the web renderer. `checkPlayer` here uses the web app's API client (`apps/web/src/lib/api` or the fetch wrapper used elsewhere in `lib/catalog.ts`).

- [ ] **Step 1: Extend the web `FormField` type**

In `apps/web/src/lib/catalog.ts`, add the same `FieldCheck` interface and `check?: FieldCheck | null` on `FormField` as in Task 8, Step 1.

- [ ] **Step 2: Add the web API wrapper**

Create `apps/web/src/lib/player-check.ts` mirroring Task 8 Step 2, but using the web app's POST helper (match how `apps/web/src/lib/catalog.ts` performs requests — same base URL / fetch wrapper). Return `PlayerCheckResult { valid, name, reason }`.

- [ ] **Step 3: Write the failing component test**

Create `apps/web/src/components/store/PurchasePanel.test.tsx` (or extend an existing one) with the same two cases as Task 9 Step 2, adapted to how `PurchasePanel` is rendered (it needs a product with a checkable field). Mock `@/lib/player-check`.

- [ ] **Step 4: Run to verify it fails**

Run: `cd apps/web && pnpm exec vitest run src/components/store/PurchasePanel.test.tsx`
Expected: FAIL — no check button.

- [ ] **Step 5: Implement in `PurchasePanel.tsx`**

In the fields map (`{fields.map((f) => ...)}`, ~line 317), when `f.check` is set render a "Проверить" button + result next to the input, with the same idle/loading/done state machine as Task 9 Step 4, reading the server value from `values[f.check.server_field]`. Use the store namespace `t(...)` already imported in this component. Reset the result when the field value changes.

- [ ] **Step 6: i18n**

Ensure `field.check` / `field.checking` / `field.checkNickname` / `field.checkFailed` exist in the namespace `PurchasePanel` uses across ru/en/uz (add them if the web store uses a different namespace than the miniapp).

- [ ] **Step 7: Run tests + typecheck**

Run: `cd apps/web && pnpm exec vitest run src/components/store/PurchasePanel.test.tsx && pnpm exec tsc --noEmit`
Expected: PASS + no type errors.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/lib/catalog.ts apps/web/src/lib/player-check.ts apps/web/src/components/store/PurchasePanel.tsx apps/web/src/components/store/PurchasePanel.test.tsx packages/i18n/locales
git commit -m "feat(web): player-check button in the purchase panel"
```

---

## Task 11: Docs — ADR, module README, cache keys

**Files:**

- Create: `docs/decisions/0031-storefront-player-check.md`
- Modify: `apps/api/src/yupay/modules/catalog/README.md` (form-schema section)
- Modify: `docs/architecture/cache-keys.md`

- [ ] **Step 1: Write ADR-0031**

Use the MADR template (`docs/decisions/0000-template.md`). Record: the public storefront player-check endpoint; the **advisory** decision; the `check` descriptor on `FormField`; and the **§10 deviation** (one synchronous external call in the handler) with its justification (advisory, user-initiated, off the order path, short-timeout, Redis-cached, mirrors the existing admin route). Reference the spec `docs/superpowers/specs/2026-07-16-storefront-player-check-design.md`.

- [ ] **Step 2: Document the `check` descriptor**

In `apps/api/src/yupay/modules/catalog/README.md`, in the "Form schema (`required_fields`)" section, add the `check` property with the jsonc example from the spec and a one-line note that it opts the field into the storefront nickname lookup.

- [ ] **Step 3: Document the cache key**

In `docs/architecture/cache-keys.md`, add a row for `playercheck:g2b:{game_code}:{server_id|-}:{player_id}` — value: JSON `PlayerCheckOut`; TTL 300s; invalidation: TTL only.

- [ ] **Step 4: Commit**

```bash
git add docs/decisions/0031-storefront-player-check.md apps/api/src/yupay/modules/catalog/README.md docs/architecture/cache-keys.md
git commit -m "docs: ADR-0031 storefront player-check + schema/cache notes"
```

---

## Task 12: Full local CI gate

**Files:** none (verification only)

- [ ] **Step 1: Python lint + types + tests**

Run: `make lint-py && make typecheck && cd apps/api && uv run pytest tests/unit tests/integration -q`
Expected: all green; coverage for `integrations` player-check paths ≥ the adapter gate.

- [ ] **Step 2: TS lint + types + tests**

Run: `make lint-ts && cd apps/miniapp && pnpm exec vitest run && cd ../web && pnpm exec vitest run`
Expected: all green.

- [ ] **Step 3: OpenAPI drift check**

Run: `make gen-api && git diff --exit-code docs/api/openapi.json packages/api-client`
Expected: no diff (Task 7 already committed the regen).

- [ ] **Step 4: Final commit if anything regenerated**

```bash
git add -A && git commit -m "chore: sync generated artifacts for check-player" || echo "nothing to commit"
```

---

## Self-review notes

- **Spec coverage:** form-schema (T1), endpoint + resolution + cache + PII + §10 (T3/T4/T5), rate-limit (T4/T5), both frontends (T9/T10), seed (T6), ADR + README + cache-keys (T11), gen-api (T7). All spec sections mapped.
- **Advisory invariant:** upstream errors and missing mapping return `{valid:false}` (T3), never 5xx; only truly bad requests 400/404.
- **Boundary:** route + service live in `integrations` (owns g2b client + mapping); URL namespaced `/catalog`. No `catalog → integrations` edge.
- **Type consistency:** `PlayerCheckOut{valid,name,reason}` (API) ↔ `PlayerCheckResult{valid,name,reason}` (TS) ↔ `_map_response` output — aligned across tasks.
