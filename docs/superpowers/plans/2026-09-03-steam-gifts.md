# Steam Gifts (G-Engine gifts-apps) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sell any of G-Engine's ~4 241 Steam games as gifts delivered to the buyer's Steam account, through a live-proxied catalog section and a dynamic-checkout service SKU, behind a dark-deploy flag.

**Architecture:** New `gifts` backend module proxies G-Engine's `/gifts/apps` catalog through Redis (stale-while-error), computes sell prices as `supplier_price(zone) × (1 + margin) × fx`, and validates gift order lines at checkout (server re-price, ±2 % tolerance). Fulfilment extends the existing `gengine` Fulfiller with a `gift` mapping kind that creates `/gifts/orders` and treats `shipped` as success, riding the existing 60 s `gengine_reconcile` poll. The storefront gets a custom `/store/steam-gifts` section (hot offers, debounced search, game page with edition/region selectors). Margin is an admin-editable DB setting.

**Tech Stack:** FastAPI + SQLAlchemy 2 async + Redis 7 (backend), respx (contract tests), Next.js 15 App Router + TanStack Query v5 (web), Vite + React 19 (admin).

**Spec:** `docs/superpowers/specs/2026-09-02-steam-gifts-design.md`

## Global Constraints

- Python: ruff (line 100), **mypy --strict**, no `Any` without an inline justification comment, Google docstrings on public functions, async everywhere on the request path.
- Money: `Decimal` in Python, `string` in TS; customer USD prices quantized to 2 dp with `ROUND_HALF_UP`.
- All new public write endpoints accept `Idempotency-Key`; admin PATCH follows the fx replay pattern (`load_replay`/`save_replay`).
- i18n: every new user-facing string lands in `ru.json`, `en.json`, `uz.json` of `packages/i18n/locales/*/web.json` in the same task. Never hardcode user-facing strings in TS.
- Feature is dark by default: `STEAM_GIFTS_ENABLED=false`; every public gifts endpoint 404s when disabled; checkout refuses gift lines when disabled.
- Region zones (fixed enum from G-Engine, spec § 2): offered list default `CIS,RU,KZ,UA`, default zone `CIS`.
- Price tolerance at checkout: refuse when server price differs from the client's by more than ±2 %.
- Fulfilment success = supplier status `shipped` (or `delivered`); `canceled`/`refunded`/`is_refunded=true` = failed.
- **Never auto re-create a gift order after an ambiguous failure** — adopt-or-park (manual review), a double gift is unrecoverable money.
- Coverage: fulfilment/supplier changes ≥ 95 %; new module ≥ 80 %.
- Every new Redis key is documented in `docs/architecture/cache-keys.md` in the same task that introduces it.
- Conventional Commits; do NOT push or deploy — local commits only.
- Frontend: TS strict, no `any`; Server Components by default; `"use client"` as deep as possible.
- Do not renumber: Alembic head is `0063_steam_links` → new migration is `0064_steam_gifts`. Next ADR number is `0066`.

### Upstream contract (verified live 2026-09-02/03, OpenAPI v2.1)

- `GET /gifts/apps?limit≤100&offset&search(max 36 chars)&sort&filters` → `{"total": int, "items": [AppResponse]}`. `AppResponse`: `{id, name, type, image, parent_id, description, dlc[], dlc_ids[], packages[], package_ids[], tags, price, discount_percent, discount_type, discount_end_date, parent}`.
- `GET /gifts/apps/{app_id}` → full `AppResponse`; each `packages[]` entry (`PackageResponse`) = `{id, name, image, prices[], apps[], discount_percent, discount_type, discount_end_date}`; `prices[]` entry (`PackagePriceResponse`) = `{region, currency, price: number|null, zone, flag_url}` — **41 zones per package, `zone` is the enum key (e.g. `CIS`), `price` is the wholesale USD figure** (`currency` is informational Steam-store currency).
- `POST /gifts/orders {invite_url, package_id, region}` → `GiftsOrderResponse` `{id, uuid, steam_id, invite_url, region, purchase_price, status, error, is_refunded, created_at, updated_at, package{id, name, apps[]}}`. **No client-supplied uuid** (unlike recharge) — see the adopt-don't-rebuy rule.
- `GET /gifts/orders?search&date_from&limit` and `GET /gifts/orders/{order_id}` → same shape.
- Statuses: `accepted → prepared → delivering → shipped → delivered`; terminal failures `canceled`, `refunded`.
- Both envelope styles exist upstream; the existing `_unwrap` in `gengine_client.py` already handles them.

---

### Task 1: G-Engine client — gifts endpoints

**Files:**

- Modify: `apps/api/src/yupay/modules/fulfillment/suppliers/gengine_client.py` (311 LOC now; additions ≈ 90 — stays under the 500 hard split line, note the 400 soft limit is knowingly crossed)
- Test: `apps/api/tests/contract/test_gengine_client.py` (append)

**Interfaces:**

- Consumes: existing `GEngineClient._request`, `_unwrap`, `GEngineError`, `GEngineUnavailableError`, `MAX_PAGE`.
- Produces (used by Tasks 3, 4, 5):
  - `@dataclass(frozen=True) GEngineGiftOrder`: `id: int`, `uuid: str`, `status: str`, `purchase_price: float`, `is_refunded: bool`, `invite_url: str`, `region: str`, `package_id: int`, `package_name: str`, `error: str | None`
  - `async def list_gift_apps(self, *, limit: int = MAX_PAGE, offset: int = 0, search: str | None = None) -> tuple[list[dict[str, Any]], int]` (items, total)
  - `async def get_gift_app(self, app_id: int) -> dict[str, Any]`
  - `async def create_gift_order(self, *, invite_url: str, package_id: int, region: str) -> GEngineGiftOrder`
  - `async def get_gift_order(self, order_id: int) -> GEngineGiftOrder`
  - `async def list_gift_orders(self, *, search: str | None = None, date_from: str | None = None, limit: int = MAX_PAGE) -> list[GEngineGiftOrder]`
- `GIFT_SEARCH_MAX = 36` module constant (server rejects longer `search`).

- [ ] **Step 1: Write the failing contract tests** (append to `apps/api/tests/contract/test_gengine_client.py`, follow the existing respx style and `BASE` constant in that file):

```python
_GIFT_ORDER_BODY = {
    "id": 990,
    "uuid": "ge-uuid-990",
    "steam_id": "76561198999918080",
    "invite_url": "https://steamcommunity.com/profiles/76561198999918080/",
    "region": "CIS",
    "purchase_price": 1.02,
    "status": "accepted",
    "error": None,
    "is_refunded": False,
    "created_at": "2026-09-03T10:00:00Z",
    "updated_at": "2026-09-03T10:00:00Z",
    "package": {"id": 55, "name": "Dead Cells", "apps": [{"id": 1, "name": "Dead Cells", "type": "game"}]},
}


@respx.mock
async def test_gift_apps_come_back_with_a_total() -> None:
    route = respx.get(f"{BASE}/gifts/apps").mock(
        return_value=httpx.Response(200, json={"total": 4241, "items": [{"id": 588650, "name": "Dead Cells"}]})
    )
    items, total = await _client().list_gift_apps(limit=25, offset=0, search="dead")
    assert total == 4241
    assert items[0]["id"] == 588650
    assert route.calls.last.request.url.params["search"] == "dead"


@respx.mock
async def test_gift_search_longer_than_the_server_cap_is_truncated_not_422d() -> None:
    route = respx.get(f"{BASE}/gifts/apps").mock(
        return_value=httpx.Response(200, json={"total": 0, "items": []})
    )
    await _client().list_gift_apps(search="x" * 50)
    assert len(route.calls.last.request.url.params["search"]) == 36


@respx.mock
async def test_creating_a_gift_order_posts_the_three_fields_and_parses_the_package() -> None:
    route = respx.post(f"{BASE}/gifts/orders").mock(
        return_value=httpx.Response(200, json=_GIFT_ORDER_BODY)
    )
    order = await _client().create_gift_order(
        invite_url="https://steamcommunity.com/profiles/76561198999918080/",
        package_id=55,
        region="CIS",
    )
    import json as _json

    sent = _json.loads(route.calls.last.request.content)
    assert sent == {
        "invite_url": "https://steamcommunity.com/profiles/76561198999918080/",
        "package_id": 55,
        "region": "CIS",
    }
    assert order.id == 990
    assert order.package_id == 55
    assert order.package_name == "Dead Cells"
    assert order.status == "accepted"


@respx.mock
async def test_gift_orders_listing_unpacks_items() -> None:
    respx.get(f"{BASE}/gifts/orders").mock(
        return_value=httpx.Response(200, json={"total": 1, "items": [_GIFT_ORDER_BODY]})
    )
    orders = await _client().list_gift_orders(search="76561198999918080")
    assert [o.id for o in orders] == [990]


@respx.mock
async def test_a_gift_order_fetch_maps_refund_and_error_fields() -> None:
    body = dict(_GIFT_ORDER_BODY, status="refunded", is_refunded=True, error="declined by recipient")
    respx.get(f"{BASE}/gifts/orders/990").mock(return_value=httpx.Response(200, json=body))
    order = await _client().get_gift_order(990)
    assert order.is_refunded is True
    assert order.error == "declined by recipient"
```

Use the file's existing `_client()` helper (or its equivalent construction) — read the top of the test file first and reuse its fixtures/`BASE`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/api && uv run pytest tests/contract/test_gengine_client.py -k gift -v`
Expected: FAIL — `AttributeError: 'GEngineClient' object has no attribute 'list_gift_apps'`.

- [ ] **Step 3: Implement in `gengine_client.py`**

Add after `GEngineOrder`:

```python
#: The server rejects a gifts `search` longer than this (422), so truncate.
GIFT_SEARCH_MAX = 36


@dataclass(frozen=True)
class GEngineGiftOrder:
    """One Steam-gift order as G-Engine reports it.

    ``package_id``/``package_name`` are flattened out of the nested
    ``package`` object because every caller wants to match on the id and
    show the name, and none of them want the tree.
    """

    id: int
    uuid: str
    status: str
    purchase_price: float
    is_refunded: bool
    invite_url: str
    region: str
    package_id: int
    package_name: str
    error: str | None
```

Add a module-level parser next to the other `_parse_*` helpers (or inline in the class if the file has none):

```python
def _gift_order(data: Any) -> GEngineGiftOrder:
    """Parse one gifts-order payload, tolerating a missing package block."""
    package = data.get("package") or {}
    return GEngineGiftOrder(
        id=int(data["id"]),
        uuid=str(data.get("uuid") or ""),
        status=str(data.get("status") or ""),
        purchase_price=float(data.get("purchase_price") or 0),
        is_refunded=bool(data.get("is_refunded")),
        invite_url=str(data.get("invite_url") or ""),
        region=str(data.get("region") or ""),
        package_id=int(package.get("id") or 0),
        package_name=str(package.get("name") or ""),
        error=(str(data["error"]) if data.get("error") else None),
    )
```

Add methods to `GEngineClient` (mirror `list_shop_products` for param handling; every response goes through `_unwrap` exactly like the existing calls):

```python
    # ---------- gifts (Steam gift games) ----------

    async def list_gift_apps(
        self,
        *,
        limit: int = MAX_PAGE,
        offset: int = 0,
        search: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """One page of the gifts catalog: (items, total)."""
        params: dict[str, Any] = {"limit": min(limit, MAX_PAGE), "offset": offset}
        if search:
            params["search"] = search[:GIFT_SEARCH_MAX]
        data = await self._request("GET", "/gifts/apps", params=params)
        return list(data.get("items") or []), int(data.get("total") or 0)

    async def get_gift_app(self, app_id: int) -> dict[str, Any]:
        """Full app card: packages with per-zone prices, DLC list."""
        data = await self._request("GET", f"/gifts/apps/{app_id}")
        return dict(data)

    async def create_gift_order(
        self, *, invite_url: str, package_id: int, region: str
    ) -> GEngineGiftOrder:
        """Create-and-buy a gift. There is no reserve step and no client uuid."""
        data = await self._request(
            "POST",
            "/gifts/orders",
            json={"invite_url": invite_url, "package_id": package_id, "region": region},
        )
        return _gift_order(data)

    async def get_gift_order(self, order_id: int) -> GEngineGiftOrder:
        data = await self._request("GET", f"/gifts/orders/{order_id}")
        return _gift_order(data)

    async def list_gift_orders(
        self,
        *,
        search: str | None = None,
        date_from: str | None = None,
        limit: int = MAX_PAGE,
    ) -> list[GEngineGiftOrder]:
        """Recent gift orders, for adopting a create whose response was lost."""
        params: dict[str, Any] = {"limit": min(limit, MAX_PAGE)}
        if search:
            params["search"] = search[:GIFT_SEARCH_MAX]
        if date_from:
            params["date_from"] = date_from
        data = await self._request("GET", "/gifts/orders", params=params)
        return [_gift_order(item) for item in (data.get("items") or [])]
```

Extend `__all__` with `GEngineGiftOrder` and `GIFT_SEARCH_MAX`. If `_request` returns the raw unwrapped payload as `Any`, keep the `dict()`/`list()` coercions above so mypy --strict passes without `Any` leaking.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd apps/api && uv run pytest tests/contract/test_gengine_client.py -v`
Expected: all PASS (old tests too).

- [ ] **Step 5: Lint + typecheck the touched file, commit**

Run: `cd apps/api && uv run ruff check src/yupay/modules/fulfillment/suppliers/gengine_client.py && uv run mypy src/yupay/modules/fulfillment/suppliers/gengine_client.py`

```bash
git add apps/api/src/yupay/modules/fulfillment/suppliers/gengine_client.py apps/api/tests/contract/test_gengine_client.py
git commit -m "feat(api/fulfillment): g-engine gifts endpoints on the supplier client"
```

---

### Task 2: `gifts` module skeleton — settings, migration 0064, admin endpoints

**Files:**

- Create: `apps/api/src/yupay/modules/gifts/__init__.py`, `api.py`, `models.py`, `settings.py`, `schemas.py`, `admin.py`, `README.md`
- Create: `apps/api/migrations/versions/0064_steam_gifts.py`
- Modify: `apps/api/src/yupay/core/config.py` (new env fields, next to the `gengine_*` block at ~:609)
- Modify: `apps/api/src/yupay/modules/integrations/models.py:66-69` (widen mapping-kind CHECK)
- Modify: `apps/api/src/yupay/modules/integrations/schemas.py` (`MappingKind` literal + `'gift'`)
- Modify: `apps/api/src/yupay/api/v1/__init__.py` (mount `gifts_admin_router`; public router mounts in Task 3)
- Test: `apps/api/tests/unit/test_gifts_settings.py`, `apps/api/tests/integration/test_gifts_admin_settings.py`

**Interfaces:**

- Consumes: `yupay.core.redis.get_redis`, `yupay.modules.admin.deps.require_admin`, fx replay helpers (find `load_replay`/`save_replay` used in `fx/routes.py:196-249` and import from the same place).
- Produces (used by Tasks 3, 4, 7):
  - Model `SteamGiftSettings` (table `steam_gift_settings`): `id: int` PK (always 1), `margin_percent: Decimal` `Numeric(10, 4)` NOT NULL, `updated_by: str | None` FK `users.id`, `updated_at: datetime`.
  - `async def load_margin_percent(db: AsyncSession) -> Decimal` — Redis (`gifts:margin`, TTL 3600) → DB row 1 → env default `settings.steam_gifts_margin_percent`, with cache write-back.
  - `async def save_margin_percent(db: AsyncSession, *, value: Decimal, admin_id: str) -> None` (DB only, `flush`, no cache write) and `async def publish_margin(value: Decimal) -> None` (called by the route **after** commit — same invariant as `fx/quote_settings.py:120-128`).
  - `def offered_zones(settings: Settings) -> list[str]` (CSV split of `steam_gifts_regions`, upper-cased, deduped, order kept) and `def default_zone(settings: Settings) -> str`.
  - Config fields: `steam_gifts_enabled: bool = False`, `steam_gifts_margin_percent: Decimal = Decimal("10")`, `steam_gifts_region_default: str = "CIS"`, `steam_gifts_regions: str = "CIS,RU,KZ,UA"`.
  - Admin routes: `GET /admin/gifts/settings` → `GiftsAdminSettingsOut {margin_percent: Decimal, enabled: bool, region_default: str, regions: list[str]}`; `PATCH /admin/gifts/settings` body `GiftsSettingsIn {margin_percent: Decimal}` (`Field(ge=0, le=100, max_digits=10, decimal_places=4)`), Idempotency-Key replay, audit-style `updated_by` from the admin actor.
  - Constant in `gifts/__init__.py` or `api.py`: `STEAM_GIFT_SKU_CODE = "steam-gift"`.

**Migration `0064_steam_gifts.py`** (`down_revision = "0063_steam_links"`; copy the style of `0063_steam_links.py`):

1. `op.create_table("steam_gift_settings", ...)` with `sa.CheckConstraint("margin_percent >= 0", name="ck_steam_gift_settings_margin_nonneg")` and `sa.CheckConstraint("id = 1", name="ck_steam_gift_settings_singleton")`.
2. Widen the mapping-kind CHECK:

```python
op.drop_constraint("ck_sku_supplier_mapping_kind", "sku_supplier_mapping", type_="check")
op.create_check_constraint(
    "ck_sku_supplier_mapping_kind",
    "sku_supplier_mapping",
    "kind IN ('voucher','game','gift')",
)
```

Downgrade restores `('voucher','game')` (and drops the settings table). Update the model's inline CHECK at `integrations/models.py:66-69` to match, and widen the `MappingKind` literal in `integrations/schemas.py` (find its definition; add `"gift"`).

**`gifts/settings.py` sketch:**

```python
_MARGIN_KEY = "gifts:margin"
_MARGIN_TTL_SECONDS = 3600


async def load_margin_percent(db: AsyncSession) -> Decimal:
    """The live margin: Redis → DB row → env-seeded default."""
    redis = get_redis()
    with contextlib.suppress(RedisError):
        cached = await redis.get(_MARGIN_KEY)
        if cached is not None:
            return Decimal(cached.decode() if isinstance(cached, bytes) else str(cached))
    row = await db.get(SteamGiftSettings, 1)
    value = row.margin_percent if row is not None else get_settings().steam_gifts_margin_percent
    with contextlib.suppress(RedisError):
        await redis.set(_MARGIN_KEY, str(value), ex=_MARGIN_TTL_SECONDS)
    return value
```

`save_margin_percent` upserts row 1 (`db.get` → mutate, else `db.add(SteamGiftSettings(id=1, ...))`) and `flush()`es; `publish_margin` writes the Redis key. The PATCH route: replay check → `save_margin_percent` → `db.commit()` → `publish_margin` → save replay (mirror the exact ordering of `fx/routes.py` `PATCH /rates/{quote}`).

`admin.py` declares `admin_router = APIRouter(prefix="/admin/gifts", tags=["admin:gifts"], dependencies=[Depends(require_admin)])`; `api.py` re-exports `admin_router` (and later `router`). Mount in `api/v1/__init__.py` alphabetically (`from yupay.modules.gifts.api import admin_router as gifts_admin_router`, include after `fx_admin_router`).

- [ ] **Step 1: Write the failing unit test** `tests/unit/test_gifts_settings.py`: `offered_zones` parses/uppercases/dedupes CSV; `load_margin_percent` returns the env default with no row and no cache (use the project's fakeredis/unit fixtures — read `apps/api/tests/unit/` conftest first and mirror how fx settings tests fake Redis; if none exist, monkeypatch `get_redis` with an `AsyncMock` whose `get` returns `None`).
- [ ] **Step 2: Run it** — Expected: FAIL (module does not exist).
- [ ] **Step 3: Create the migration + models + config fields**; run `make migrate` against the dev DB (or `cd apps/api && uv run alembic upgrade head` if the stack is up) and confirm `alembic heads` shows `0064_steam_gifts`.
- [ ] **Step 4: Implement `settings.py`, `schemas.py`, `admin.py`, `api.py`, `README.md`** (README: module purpose, public surface, the commit-then-publish invariant).
- [ ] **Step 5: Write the failing integration test** `tests/integration/test_gifts_admin_settings.py`: as admin, `GET /admin/gifts/settings` returns the seeded default 10; `PATCH` with `{"margin_percent": "12.5"}` + `Idempotency-Key` persists (re-GET sees 12.5); replaying the same key returns the same response without a second write; non-admin gets 403. Mirror an existing admin-route integration test for fixtures (e.g. the fx or sourcing admin tests).
- [ ] **Step 6: Run the suite** — `cd apps/api && uv run pytest tests/unit/test_gifts_settings.py tests/integration/test_gifts_admin_settings.py -v` — Expected: PASS.
- [ ] **Step 7: Lint, typecheck, commit**

```bash
cd apps/api && uv run ruff check src/yupay/modules/gifts migrations/versions/0064_steam_gifts.py && uv run mypy src/yupay/modules/gifts
git add apps/api/src/yupay/modules/gifts apps/api/migrations/versions/0064_steam_gifts.py apps/api/src/yupay/core/config.py apps/api/src/yupay/modules/integrations/models.py apps/api/src/yupay/modules/integrations/schemas.py apps/api/src/yupay/api/v1/__init__.py apps/api/tests/unit/test_gifts_settings.py apps/api/tests/integration/test_gifts_admin_settings.py
git commit -m "feat(api/gifts): module skeleton, admin-editable margin, gift mapping kind (0064)"
```

---

### Task 3: Live catalog proxy with Redis cache

**Files:**

- Create: `apps/api/src/yupay/modules/gifts/service.py`, `apps/api/src/yupay/modules/gifts/routes.py`
- Modify: `apps/api/src/yupay/modules/gifts/api.py` (export `router`), `apps/api/src/yupay/modules/gifts/schemas.py` (public DTOs), `apps/api/src/yupay/api/v1/__init__.py` (mount public router)
- Modify: `docs/architecture/cache-keys.md` (document every new key)
- Test: `apps/api/tests/unit/test_gifts_service.py`, `apps/api/tests/integration/test_gifts_catalog_routes.py`

**Interfaces:**

- Consumes: Task 1 client methods; Task 2 `load_margin_percent`, `offered_zones`, `default_zone`; `yupay.modules.fx.factory.build_default_service` + `FxService.convert` (`await fx.convert(amount, base="USD", quote="UZS")` → `ConversionResult(amount, rate, source)`); `yupay.core.errors.UpstreamUnavailableError, NotFoundError`.
- Produces (used by Tasks 4, 8, 9):
  - `def sell_price_usd(supplier_usd: Decimal, margin_percent: Decimal) -> Decimal` — `(supplier_usd * (1 + margin_percent / 100)).quantize(Decimal("0.01"), ROUND_HALF_UP)`.
  - `def zone_price_usd(package: dict[str, Any], zone: str) -> Decimal | None` — scan `package["prices"]` for `entry["zone"] == zone`, `None` when absent or `price` is null.
  - `async def list_apps(*, search: str | None, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]` — cached raw upstream items.
  - `async def get_app(app_id: int) -> dict[str, Any]` — cached detail; raises `NotFoundError` on upstream 404-refusal.
  - `async def hot_offers() -> list[dict[str, Any]]` — a curated pinned list first (`_PINNED_APP_IDS: tuple[int, ...] = ()` module constant, empty in v1 — spec § 4.2 wants it admin-editable later; each pinned id fetched via `get_app`), then scan the first `_HOT_SCAN_PAGES = 5` pages (500 items) of the default listing, keep `discount_percent > 0`, sort desc, fill up to 12 total; cached whole under `gifts:hot`.
  - Public routes (all behind an `enabled` guard dependency raising `NotFoundError` when `steam_gifts_enabled` is false):
    - `GET /gifts/catalog?search=&limit=&offset=` → `GiftsListOut {items: list[GiftAppOut], total: int}`
    - `GET /gifts/catalog/hot` → `GiftsListOut`
    - `GET /gifts/catalog/{app_id}` → `GiftAppDetailOut`
    - `GET /gifts/catalog/{app_id}/dlc?search=&limit=&offset=` → `GiftsListOut` (served by filtering/slicing the cached detail's `dlc[]` server-side — never the flat 400-item list)
  - `GiftAppOut`: `app_id: int`, `name: str`, `image: str | None`, `type: str`, `price_usd: str | None` (our 2-dp sell price for the default zone), `price_uzs: str | None` (display, whole UZS via `Intl`-ready string), `discount_percent: int | None`, `packages_count: int`, `dlc_count: int`.
  - `GiftAppDetailOut`: adds `description: str | None`, `packages: list[GiftPackageOut]`, `dlc_total: int`, `zones: list[str]` (the offered zones that actually have a price on ≥ 1 package), `zone_default: str`.
  - `GiftPackageOut`: `id: int`, `name: str`, `image: str | None`, `discount_percent: int | None`, `prices: list[GiftZonePriceOut {zone: str, price_usd: str, price_uzs: str | None}]` — **only zones from `offered_zones`**, sell prices (margin applied), never the raw wholesale figure.

**Cache design (all keys in `docs/architecture/cache-keys.md`):**

| Key                                                           | TTL    | Stale twin (`{key}:stale`) | Content                                    |
| ------------------------------------------------------------- | ------ | -------------------------- | ------------------------------------------ |
| `gifts:list:{offset}:{limit}`                                 | 3600 s | 86400 s                    | default listing page JSON `{items, total}` |
| `gifts:search:{sha1(query.lower().strip())}:{offset}:{limit}` | 900 s  | 86400 s                    | search page JSON                           |
| `gifts:detail:{app_id}`                                       | 900 s  | 86400 s                    | full AppResponse JSON                      |
| `gifts:hot`                                                   | 3600 s | 86400 s                    | hot-offer items JSON                       |
| `gifts:margin`                                                | 3600 s | —                          | margin Decimal string (Task 2)             |

One helper drives them all:

```python
async def _cached_json(key: str, ttl: int, fetch: Callable[[], Awaitable[Any]]) -> Any:
    """Fresh cache → upstream → stale-on-error. Redis being down never 500s a read."""
    redis = get_redis()
    with contextlib.suppress(RedisError):
        cached = await redis.get(key)
        if cached is not None:
            return json.loads(cached)
    try:
        value = await fetch()
    except (GEngineError, GEngineUnavailableError) as exc:
        with contextlib.suppress(RedisError):
            stale = await redis.get(f"{key}:stale")
            if stale is not None:
                log.warning("gifts.catalog_stale", key=key, error=str(exc))
                return json.loads(stale)
        raise UpstreamUnavailableError("the gifts catalog is temporarily unavailable") from exc
    payload = json.dumps(value)
    with contextlib.suppress(RedisError):
        await redis.set(key, payload, ex=ttl)
        await redis.set(f"{key}:stale", payload, ex=_STALE_TTL_SECONDS)
    return value
```

`service.py` builds its own transient client from settings (do NOT import the fulfiller — keeps `orders → gifts` free of any cycle through `fulfillment`):

```python
def _client() -> GEngineClient:
    s = get_settings()
    return GEngineClient(api_key=s.gengine_api_key, base_url=s.gengine_base_url, timeout_seconds=s.gengine_request_timeout_seconds)
```

Pricing in routes: listing rows price from the item's reference `price` field (wholesale USD) for the **default zone display only** — margin applied; rows with `price` null show `price_usd=None`. Detail prices come from `packages[].prices[]` per offered zone. UZS display: one `fx.convert` per request (fetch the USD→UZS rate once, multiply per row, round to whole UZS via `quantize(Decimal("1"))`); on `FxUnavailableError` return `price_uzs=None` rather than failing the page. Rate limiting: these routes rely on the same app-wide slowapi defaults as `/catalog/*` (no per-route bucket) — copy whatever decorator/dependency `catalog/routes.py` applies; if it applies none, apply none.

- [ ] **Step 1: Unit tests first** (`tests/unit/test_gifts_service.py`): `sell_price_usd(Decimal("0.97"), Decimal("10")) == Decimal("1.07")`; `zone_price_usd` finds CIS / returns None for a null price; `_cached_json` fresh-hit, miss-then-store, stale-on-upstream-error, raise-when-no-stale (fake Redis + a `fetch` stub that raises `GEngineUnavailableError`); `hot_offers` filters and sorts by discount.
- [ ] **Step 2: Run — FAIL** (`uv run pytest tests/unit/test_gifts_service.py -v`).
- [ ] **Step 3: Implement `service.py` + `schemas.py` DTOs.**
- [ ] **Step 4: Unit tests PASS.**
- [ ] **Step 5: Integration tests** (`tests/integration/test_gifts_catalog_routes.py`, respx-mock upstream): disabled flag → 404 on every route; enabled → listing maps fields and applies margin; detail exposes only offered zones; `/dlc` filters by search server-side; upstream down + warm stale → 200 with stale data.
- [ ] **Step 6: Run — PASS.** Also `uv run pytest tests/unit tests/integration -q` for regressions.
- [ ] **Step 7: Update `docs/architecture/cache-keys.md`, lint, typecheck, commit**

```bash
git add apps/api/src/yupay/modules/gifts docs/architecture/cache-keys.md apps/api/src/yupay/api/v1/__init__.py apps/api/tests/unit/test_gifts_service.py apps/api/tests/integration/test_gifts_catalog_routes.py
git commit -m "feat(api/gifts): live gifts catalog proxy with stale-while-error redis cache"
```

---

### Task 4: Checkout — gift order lines (server re-price, ±2 %)

**Files:**

- Create: `apps/api/src/yupay/modules/gifts/checkout.py`
- Modify: `apps/api/src/yupay/modules/orders/service.py` (item loop, right after `_resolve_line_unit_price` at ~:722)
- Modify: `apps/api/src/yupay/modules/gifts/api.py` (export `checkout` surface)
- Test: `apps/api/tests/unit/test_gifts_checkout.py`, `apps/api/tests/integration/test_checkout_steam_gift.py`

**Interfaces:**

- Consumes: Task 2 `STEAM_GIFT_SKU_CODE`, `load_margin_percent`, `offered_zones`; Task 3 `get_app`, `zone_price_usd`, `sell_price_usd`; `yupay.core.errors.ValidationError`.
- Produces (used by orders.service and Task 9's client contract):
  - `def is_gift_sku(sku: object) -> bool` — `getattr(sku, "sku_code", None) == STEAM_GIFT_SKU_CODE` (duck-typed like `is_unit_sku`).
  - `def parse_invite_url(value: str) -> str` — validates + canonicalizes (strip whitespace, enforce one of: `https://steamcommunity.com/profiles/{17 digits}`, `https://steamcommunity.com/id/{vanity 2-32 [A-Za-z0-9_-]}`, `https://s.team/p/{path}`; tolerate missing scheme and trailing slash; raise `ValidationError("invite_url is not a Steam profile or friend link")` otherwise).
  - `async def price_gift_line(db: AsyncSession, *, line_amount_usd: Decimal | None, data: dict[str, Any]) -> tuple[Decimal, dict[str, Any]]` — the authoritative unit price and the enriched snapshot.

**`price_gift_line` behaviour (each rule is a test):**

1. `steam_gifts_enabled` false → `ValidationError("steam gifts are not available right now")`.
2. `data` must carry `app_id` (int-able), `package_id` (int-able), `region` (member of `offered_zones`), `invite_url` (passes `parse_invite_url`; the canonical form is written back into the snapshot).
3. Fetch the app via `gifts.service.get_app(app_id)` (this reuses the 15-min detail cache — checkout never trusts a client-side price and never hits upstream more than once per app per 15 min). App gone / package_id not in `packages[]` → `ValidationError("this game is no longer available")`.
4. `supplier_usd = zone_price_usd(package, region)`; `None` → `ValidationError("this region has no price for the selected edition")`.
5. `expected = sell_price_usd(supplier_usd, await load_margin_percent(db))`.
6. `line_amount_usd is None` → `ValidationError("amount is required for this product")`. If `abs(line_amount_usd - expected) > expected * Decimal("0.02")` → `ValidationError("the price of this gift has changed — refresh and try again", extra={"expected_amount_usd": str(expected)})` (client re-renders from `expected_amount_usd`).
7. Enrich the snapshot: `data["app_name"] = app["name"]`, `data["package_name"] = package["name"]`, `data["supplier_price_usd"] = str(supplier_usd)` — server-derived, overwriting anything client-sent.
8. Return `(expected, data)` — the **server** price is billed even inside the tolerance band.

**Wiring in `orders/service.py` (`create_order` item loop):**

```python
cleaned = validate_fulfillment_data(product=product, data=line.fulfillment_data)
unit_price_usd = _resolve_line_unit_price(sku, line, currency)
if gifts_checkout.is_gift_sku(sku):
    unit_price_usd, cleaned = await gifts_checkout.price_gift_line(
        db, line_amount_usd=line.amount_usd, data=cleaned
    )
```

Import as `from yupay.modules.gifts import checkout as gifts_checkout` (module-level; gifts imports nothing from orders, so no cycle). Note: the SKU is `variable_amount=True` (Task 6), so `_resolve_line_unit_price` has already enforced `qty == 1`, non-USD currency, 2-dp `amount_usd` and the SKU's min/max bounds; `_compute_total_charged`'s variable branch then converts `unit_price_usd` at the guarded rate × `rate_multiplier` (=1) — no changes needed there. `quote_cart` is untouched: quotes skip fulfillment_data by design, and the panel (Task 9) quotes with the plain amount.

**`validate_fulfillment_data` interplay:** the product's `required_fields` (Task 6) declare `app_id`/`package_id` as `number`, `region` as `select`, `invite_url` as `text` with a safe pattern — so the generic validator admits exactly our four keys and rejects unknown ones _before_ the hook; the hook's own checks are the money-bearing layer on top. The snapshot keys the hook **adds** (`app_name`, `package_name`, `supplier_price_usd`) happen after validation, which is fine — only client-sent unknown keys 422.

- [ ] **Step 1: Unit tests** (`tests/unit/test_gifts_checkout.py`, monkeypatched `get_app`/`load_margin_percent`/`get_settings`): every numbered rule above, plus `parse_invite_url` accept/reject table (profiles ok, vanity ok, s.team ok, garbage/HTTP-scheme-injection rejected, canonical form returned).
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement `checkout.py`; wire `orders/service.py`.**
- [ ] **Step 4: Unit tests PASS.**
- [ ] **Step 5: Integration test** (`tests/integration/test_checkout_steam_gift.py`, respx upstream + seeded gift SKU fixture — build the SKU/product inline in the test the way `test_checkout_variable_amount.py` builds its fixtures): happy path creates the order with the server price and the enriched snapshot on the row; price drifted > 2 % → 422 with `expected_amount_usd`; disabled flag → 422; bad region → 422. Assert `OrderItem.fulfillment_data` contains `supplier_price_usd` and the canonical `invite_url`.
- [ ] **Step 6: Run — PASS**, plus `uv run pytest tests/integration/test_checkout_variable_amount.py -q` (no Stars regression).
- [ ] **Step 7: Lint, typecheck, commit**

```bash
git add apps/api/src/yupay/modules/gifts apps/api/src/yupay/modules/orders/service.py apps/api/tests/unit/test_gifts_checkout.py apps/api/tests/integration/test_checkout_steam_gift.py
git commit -m "feat(api/orders): steam-gift order lines re-priced server-side with a 2% tolerance"
```

---

### Task 5: Fulfilment — gift branch of the gengine Fulfiller

**Files:**

- Modify: `apps/api/src/yupay/modules/fulfillment/suppliers/gengine.py` (528 LOC — the gift branch adds ~120; extract it as a sibling `gengine_gifts.py` helper module called from `gengine.py` to stay under the split line)
- Create: `apps/api/src/yupay/modules/fulfillment/suppliers/gengine_gifts.py`
- Modify: `apps/api/src/yupay/modules/fulfillment/routes.py:107-123` (`_CUSTOMER_SAFE_ARTIFACT_KEYS`: add `"kind"`, `"app_name"`, `"package_name"`, `"status"`)
- Test: `apps/api/tests/unit/test_gengine_gifts_fulfiller.py`

**Interfaces:**

- Consumes: Task 1 `GEngineGiftOrder`, `create_gift_order`, `get_gift_order`, `list_gift_orders`; `base.FulfillResult`, `FulfillStatus`, `FulfillerError`; existing `_mapping_for`, task metadata plumbing (`task.extra_metadata`, merged by `service.py:486-487` and `:1017-1018`).
- Produces:
  - In `gengine_gifts.py`: `async def fulfill_gift(client: GEngineClient, *, item: OrderItem, order_created_at: datetime) -> FulfillResult` and `async def gift_status(client: GEngineClient, *, task: FulfillmentTask) -> FulfillStatus`.
  - `gengine.py` routes to them: in `fulfill()` — `if mapping.kind == "gift": return await fulfill_gift(self._client(), item=item, order_created_at=order.created_at)`; in `check_status()` — `if task.extra_metadata.get("gengine_kind") == "gift": return await gift_status(self._client(), task=task)` (this branch goes **before** the existing `external_order_id` early-return, because an id-less gift task still has work to do).
  - Existing `gengine_reconcile` job needs **no change**: it already sweeps `supplier="gengine", status="in_progress"` → `process_webhook_update` → `check_status`.

**`fulfill_gift` (money-safety is the whole design):**

```python
GIFT_STATUS_DONE = {"shipped", "delivered"}
GIFT_STATUS_DEAD = {"canceled", "refunded"}
#: An id-less gift task older than this is parked for manual review instead of
#: being re-bought: by then a landed create is findable, so absence means the
#: create never happened — and a human confirms that before any second spend.
GIFT_ADOPT_WINDOW_MINUTES = 30
```

1. Read `invite_url`, `package_id`, `region` from `item.fulfillment_data`; any missing → `FulfillerError` (non-retryable — the checkout hook made this impossible, so it is data corruption, not weather).
2. `existing = await _find_gift_order(client, invite_url=invite_url, package_id=package_id, since=order_created_at)` — `list_gift_orders(search=_search_term(invite_url), date_from=since.isoformat())`, exact-match `invite_url` **and** `package_id`, newest first. `_search_term` extracts the last path segment (steamid64 or vanity) because the full URL exceeds the 36-char search cap. Any client error during the probe → treat as not-found (the probe is best-effort; create has its own guard).
3. Found → adopt: return in_progress carrying its id (never create a second order for a retried task).
4. Not found → `create_gift_order(...)`. On `GEngineError` (clean refusal) → raise `FulfillerError(str(exc))` (usual failed path). On `GEngineUnavailableError` (**ambiguous** — the create may have landed) → return

```python
FulfillResult(
    outcome="in_progress",
    external_order_id=None,
    artifact_kind=None,
    artifact=None,
    error=None,
    extra_metadata={
        "supplier": "gengine",
        "gengine_kind": "gift",
        "gift_package_id": package_id,
        "gift_search": _search_term(invite_url),
        "gift_invite_url": invite_url,
    },
)
```

5. Created/adopted → same shape with `external_order_id=str(order.id)` and the same metadata (plus `gengine_status`).

**`gift_status`:**

1. `task.external_order_id` set → `get_gift_order(int(...))` → map:
   - status in `GIFT_STATUS_DONE` → succeeded with `artifact_kind="topup_receipt"`, `artifact={"supplier": "gengine", "kind": "gift", "external_order_id": ..., "status": ..., "app_name": <from task metadata or order.package_name>, "package_name": order.package_name, "message": "Steam прислал вам подарок — примите его в клиенте или по ссылке из письма Steam. Отправитель — бот-аккаунт магазина, это нормально."}` (RU free text is the existing precedent — g2b `_game_artifact`'s `message`; the storefront renders its own localized card in Task 9, this string is the email/miniapp fallback).
   - `is_refunded` or status in `GIFT_STATUS_DEAD` → failed with `error=order.error or f"supplier status {order.status}"`.
   - else → in_progress with `extra_metadata={"gengine_status": order.status}`.
2. No `external_order_id` → re-run the finder from metadata (`gift_search`, `gift_package_id`, `gift_invite_url`); found → in_progress with `extra_metadata={"gift_adopted_id": str(o.id)}`… **but** `FulfillStatus` cannot set `external_order_id` (recon fact) — so instead: found → poll that order directly and return its mapped status **plus** `extra_metadata={"gift_order_id": str(o.id)}`; subsequent polls read `task.extra_metadata["gift_order_id"]` first. (First check `gift_order_id` in metadata, then probe.)
3. Not found and `task.created_at` older than `GIFT_ADOPT_WINDOW_MINUTES` → failed `error="gift order not found at supplier after create timeout — manual review"`. Younger → in_progress.
4. `GEngineUnavailableError` anywhere → in_progress (the reconcile sweep retries in 60 s).

**Note on `delivered` vs `shipped`:** OUR success fires at `shipped` (spec § 4.4); `delivered` arriving first (fast recipient) is also success — hence the two-member `GIFT_STATUS_DONE`. A post-`shipped` decline surfaces as `refunded` on a task that already succeeded — that is the existing stuck/refund manual path, not this loop; nothing to code here.

- [ ] **Step 1: Unit tests** (`tests/unit/test_gengine_gifts_fulfiller.py`, injected fake client like the existing gengine fulfiller unit tests — find them via `grep -rl GEngineFulfiller apps/api/tests`): create-happy-path returns in_progress with id + metadata; adopt-before-create when the finder hits; unavailable-create returns id-less in_progress (and asserts **no** second create call on the next `fulfill_gift` run when the finder now finds it); `gift_status` full map (done both statuses, refunded, canceled, in-progress passthrough, adopt-by-metadata, park-after-window, unavailable→in_progress); artifact key allow-list covers the new keys.
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement `gengine_gifts.py` + the two routing lines in `gengine.py` + the allow-list additions.**
- [ ] **Step 4: Run — PASS**, plus the whole fulfilment suite: `uv run pytest tests/unit -k "gengine or fulfill" -q`.
- [ ] **Step 5: Coverage check** — `uv run pytest tests/unit/test_gengine_gifts_fulfiller.py --cov=yupay.modules.fulfillment.suppliers.gengine_gifts --cov-report=term` — Expected ≥ 95 %.
- [ ] **Step 6: Lint, typecheck, commit**

```bash
git add apps/api/src/yupay/modules/fulfillment/suppliers/gengine_gifts.py apps/api/src/yupay/modules/fulfillment/suppliers/gengine.py apps/api/src/yupay/modules/fulfillment/routes.py apps/api/tests/unit/test_gengine_gifts_fulfiller.py
git commit -m "feat(api/fulfillment): steam-gift branch of the g-engine fulfiller, adopt-don't-rebuy"
```

---

### Task 6: Seed — brand, product, SKU, mapping

**Files:**

- Create: `scripts/seed/2026-09-03_steam_gifts.py`

**Interfaces:**

- Consumes: Task 2's widened `gift` mapping kind; the catalog models; the style/structure of `scripts/seed/2026-08-21_telegram_stars_unit_sku.py` (async session bootstrap, idempotent upserts, `--apply` dry-run convention — read it first and mirror it).
- Produces: DB rows the whole feature hangs on —
  - Brand `steam-gifts` («Steam Гифты» ru / "Steam Gifts" en / "Steam sovg'alari" uz), active, in the same category as the existing `steam` brand (look it up at runtime; fall back to the first active category with a warning).
  - Product slug `steam-gift`, `kind="top_up"`, translations in 3 locales, `required_fields`:

```python
REQUIRED_FIELDS = [
    {"key": "app_id", "label": {"ru": "ID игры", "en": "App ID", "uz": "O'yin ID"}, "type": "number", "required": True},
    {"key": "package_id", "label": {"ru": "Издание", "en": "Edition", "uz": "Nashr"}, "type": "number", "required": True},
    {
        "key": "region",
        "label": {"ru": "Регион", "en": "Region", "uz": "Mintaqa"},
        "type": "select",
        "required": True,
        "options": [
            {"value": "CIS", "label": {"ru": "СНГ (без России)", "en": "CIS (no Russia)", "uz": "MDH (Rossiyasiz)"}},
            {"value": "RU", "label": {"ru": "Россия", "en": "Russia", "uz": "Rossiya"}},
            {"value": "KZ", "label": {"ru": "Казахстан", "en": "Kazakhstan", "uz": "Qozog'iston"}},
            {"value": "UA", "label": {"ru": "Украина", "en": "Ukraine", "uz": "Ukraina"}},
        ],
    },
    {
        "key": "invite_url",
        "label": {"ru": "Ссылка на профиль Steam", "en": "Steam profile link", "uz": "Steam profil havolasi"},
        "type": "text",
        "required": True,
        "pattern": r"^(https?://)?(steamcommunity\.com/(profiles/\d{17}|id/[A-Za-z0-9_-]{2,32})|s\.team/p/[A-Za-z0-9/_-]+)/?$",
    },
]
```

(Before writing, confirm `FormOption`'s exact field names in `catalog/schemas.py` — `value`/`label` with `LocaleMap` labels — and match them; the checkout hook re-validates region against settings anyway, so the option list here is UX, not the security boundary.)

- SKU `sku_code="steam-gift"`, `price_usd=Decimal("1")` (unused placeholder — the column is NOT NULL), `variable_amount=True`, `min_amount_usd=Decimal("0.50")`, `max_amount_usd=Decimal("300")`, `rate_multiplier=Decimal("1")`, `active=True` (mirror `2026-08-18_telegram_stars_any_amount.py:106-110`).
- Mapping row in `sku_supplier_mapping`: `(sku_id, 'gengine')`, `kind='gift'`, `external_product_id='gifts-apps'` (informational — the fulfiller routes on `kind`), `quantity=1`, `is_active=True`. Insert directly with SQLAlchemy (do **not** call `integrations.service.upsert_mapping`, whose cost-refresh path knows nothing about gifts).
- No sourcing rule needed: product kind `top_up` + a single active mapping → `sourcing._resolve_auto` yields `supplier:gengine`.

- [ ] **Step 1: Write the script** with a `--apply` flag (dry-run prints intended writes), idempotent re-runs (upsert by slug/sku_code/PK), and a final verification query printing the created ids.
- [ ] **Step 2: Run against the dev stack** — `make dev` (if not up), then `cd apps/api && uv run python ../../scripts/seed/2026-09-03_steam_gifts.py` (dry-run) and `... --apply`. Expected: second `--apply` run reports "already present" and changes nothing.
- [ ] **Step 3: Smoke-check the checkout path end-to-end on dev** — with `STEAM_GIFTS_ENABLED=true` in the api env and respx-free reality: `curl localhost:8000/api/v1/gifts/catalog?limit=3` (real upstream if the key is configured; otherwise skip), and a `POST /orders` with a gift line asserting a 422 `expected_amount_usd` round-trips.
- [ ] **Step 4: Lint (`ruff check scripts/seed/2026-09-03_steam_gifts.py`), commit**

```bash
git add scripts/seed/2026-09-03_steam_gifts.py
git commit -m "feat(seed): steam-gifts brand, dynamic steam-gift SKU and gengine gift mapping"
```

---

### Task 7: Admin SPA — Steam Gifts settings page

**Files:**

- Create: `apps/admin/src/features/gifts/GiftsSettingsPage.tsx`, `apps/admin/src/features/gifts/types.ts`, `apps/admin/src/features/gifts/GiftsSettingsPage.test.tsx`
- Modify: `apps/admin/src/app/router.tsx` (route `/gifts`), `apps/admin/src/app/Layout.tsx` (nav item in the «Системное» group: `{ to: "/gifts", label: "Steam Гифты", icon: Gift }` — `Gift` from `lucide-react`), `apps/admin/src/lib/queryKeys.ts` (`giftsSettings: () => ["gifts", "settings"] as const`)

**Interfaces:**

- Consumes: Task 2 endpoints `GET/PATCH /api/v1/admin/gifts/settings`; `apiGet`/`apiPatch` from `apps/admin/src/lib/api.ts`; form pattern from `apps/admin/src/features/fx/FxRateCard.tsx` (local state mirror, `dirty`/`canSave`, disabled-while-saving button).
- Produces: `types.ts`:

```ts
export interface GiftsAdminSettings {
  margin_percent: string;
  enabled: boolean;
  region_default: string;
  regions: string[];
}
```

Page behaviour: `useQuery({ queryKey: qk.giftsSettings(), queryFn: () => apiGet<GiftsAdminSettings>("/admin/gifts/settings") })`; a card showing the flag state (read-only badge «Выключено» / «Включено» — the flag is env-driven), the region list (read-only chips), and one editable decimal input for `margin_percent` (`inputMode="decimal"`, validate 0–100) with «Сохранить»; `useMutation` PATCHes `{ margin_percent }` with an `Idempotency-Key` header (`crypto.randomUUID()`), `onSuccess` → `qc.setQueryData(qk.giftsSettings(), next)`. Admin SPA is RU-only (existing convention — labels hardcoded in Russian like the rest of the admin).

- [ ] **Step 1: Test first** (`GiftsSettingsPage.test.tsx`, Vitest + Testing Library, mock `lib/api`): renders the loaded margin; save button disabled until the value changes; PATCH called with the typed value; error path shows the shared error state. Mirror `FxPage.test.tsx` scaffolding.
- [ ] **Step 2: Run — FAIL** — `pnpm --filter admin test -- --run GiftsSettingsPage`.
- [ ] **Step 3: Implement page + route + nav + query key.**
- [ ] **Step 4: Run — PASS**, then `pnpm --filter admin test -- --run` and `pnpm --filter admin exec tsc --noEmit`.
- [ ] **Step 5: Commit**

```bash
git add apps/admin/src/features/gifts apps/admin/src/app/router.tsx apps/admin/src/app/Layout.tsx apps/admin/src/lib/queryKeys.ts
git commit -m "feat(admin): steam gifts settings page with editable margin"
```

---

### Task 8: Web — section page `/store/steam-gifts` (hot offers, search, grid)

**Files:**

- Create: `apps/web/src/lib/gifts.ts` (server+client fetchers, DTO types)
- Create: `apps/web/src/app/[locale]/store/steam-gifts/page.tsx` (server, ISR)
- Create: `apps/web/src/components/gifts/GiftsBrowser.tsx` (client: search + grid + pagination), `apps/web/src/components/gifts/GiftCard.tsx` (server-usable presentational card), `apps/web/src/components/gifts/HotOffers.tsx` (server component carousel/strip)
- Modify: `packages/i18n/locales/{ru,en,uz}/web.json` (namespace `gifts`)
- Test: `apps/web/src/lib/gifts.test.ts`, `apps/web/src/components/gifts/GiftsBrowser.test.tsx`

**Interfaces:**

- Consumes: Task 3 public endpoints; `lib/api.ts` `apiGet`/`apiGetOrNull` (server, ISR tags) and `lib/client.ts` `apiFetch` (client); `lib/image.ts::isOptimizable`; `lib/seo.ts` helpers; translation pattern `getTranslations("web.gifts")`.
- Produces (used by Task 9):

```ts
export interface GiftApp {
  app_id: number;
  name: string;
  image: string | null;
  type: string;
  price_usd: string | null;
  price_uzs: string | null;
  discount_percent: number | null;
  packages_count: number;
  dlc_count: number;
}
export interface GiftsList {
  items: GiftApp[];
  total: number;
}
// server: cached ISR fetches that NEVER throw at build time (deployed API may predate the feature)
export async function getGiftsHot(locale: string): Promise<GiftApp[]>; // [] on any error
export async function getGiftsPage(locale: string, offset?: number): Promise<GiftsList>; // {items:[],total:0} on error
// client: used by GiftsBrowser via TanStack Query
export async function searchGifts(locale: string, q: string, offset: number): Promise<GiftsList>;
```

**Page composition** (`page.tsx`, `export const revalidate = 300`): metadata via `alternates(locale, "/store/steam-gifts")` + title/description from `web.gifts.meta`; hero (title, subtitle, «как это работает» 3-step strip — pure i18n text); `<HotOffers items={hot} />` when non-empty; `<GiftsBrowser locale={locale} initial={firstPage} />`; `ItemList` JSON-LD **of hot offers only** (spec § 5 — live prices for 4k items would churn the crawl) via `JsonLd`; empty-state «раздел скоро откроется» when both fetches came back empty (dark-deploy renders harmlessly). The `steam-gifts` brand row (Task 6) makes the slug appear in `getBrandSlugs()`/sitemap automatically; the static `store/steam-gifts` segment wins over `[brandSlug]` in App Router — no sitemap change needed.

**GiftsBrowser** (client): `useState` query + 400 ms `setTimeout` debounce (mirror `PromoField.tsx:49,193-213` — deliberate `apiFetch`-in-effect is fine, but prefer `useQuery({ queryKey: ["gifts", q, offset], queryFn: ..., placeholderData: keepPreviousData })` since this endpoint is cache-backed); empty query renders `initial` (server-fetched, no client fetch); grid of `GiftCard` (cover with `isOptimizable` guard, name, «Изданий: N · DLC: M» from i18n plurals via ICU, UZS price via `Intl.NumberFormat`, discount badge); «Показать ещё» pagination by offset; loading skeletons; error state with retry.

**i18n keys** (all three locales in this task): `web.gifts.meta.{title,description}`, `web.gifts.hero.{title,subtitle,step1..step3}`, `web.gifts.search.{placeholder,empty,error,retry,showMore}`, `web.gifts.card.{editions,dlc}` (ICU plural), `web.gifts.badge.discount`, `web.gifts.comingSoon`.

- [ ] **Step 1: Tests first**: `gifts.test.ts` — fetchers return safe fallbacks on network error/404 (mock `fetch`); `GiftsBrowser.test.tsx` — renders initial items, debounces (fake timers) into one fetch for "dead", renders results and empty state. Mirror existing web component tests for setup.
- [ ] **Step 2: Run — FAIL** — `pnpm --filter web test -- --run gifts`.
- [ ] **Step 3: Implement lib + components + page + locale keys.**
- [ ] **Step 4: Run — PASS**, then `pnpm --filter web exec tsc --noEmit` and `pnpm --filter web lint`. CI checks locale-key parity — verify all three files got every key.
- [ ] **Step 5: Visual smoke on dev** (`make dev-web` + api with flag on): section renders, search works, hot offers show. (Remember the memory note: never host-build web while the dev container is up.)
- [ ] **Step 6: Commit**

```bash
git add apps/web/src/lib/gifts.ts apps/web/src/lib/gifts.test.ts apps/web/src/app/[locale]/store/steam-gifts apps/web/src/components/gifts packages/i18n/locales
git commit -m "feat(web): steam gifts section — hot offers, debounced search, grid"
```

---

### Task 9: Web — game page, purchase panel, post-purchase instructions

**Files:**

- Create: `apps/web/src/app/[locale]/store/steam-gifts/[appId]/page.tsx` (server; `revalidate = 300`, no `generateStaticParams` — on-demand ISR across 4 241 ids)
- Create: `apps/web/src/components/gifts/GiftPurchasePanel.tsx` (client), `apps/web/src/components/gifts/DlcBrowser.tsx` (client, lazy search+pagination over `/dlc`), `apps/web/src/components/gifts/InviteGuide.tsx` (static illustrated hint)
- Modify: `apps/web/src/lib/gifts.ts` (detail fetchers + checkout types)
- Modify: `apps/web/src/components/order/OrderStatus.tsx` (gift delivery card)
- Modify: `packages/i18n/locales/{ru,en,uz}/web.json` (extend `gifts`)
- Test: `apps/web/src/components/gifts/GiftPurchasePanel.test.tsx`, `apps/web/src/components/gifts/DlcBrowser.test.tsx`

**Interfaces:**

- Consumes: Task 3 detail/DLC endpoints; Task 4's checkout contract; Task 6's SKU (resolved at render: the page ALSO fetches `getBrandDetail("steam-gifts", locale, "UZS")` and takes the single product's single variable SKU id — same data path every brand page already uses); checkout POST flow copied from `PurchasePanel.tsx:1355-1443` (guest token mint, Idempotency-Key, `payments/intents`, redirect) — extract the minimal shared bits into `apps/web/src/lib/gift-checkout.ts` rather than importing the 2 100-line panel.
- Produces:

```ts
export interface GiftZonePrice {
  zone: string;
  price_usd: string;
  price_uzs: string | null;
}
export interface GiftPackage {
  id: number;
  name: string;
  image: string | null;
  discount_percent: number | null;
  prices: GiftZonePrice[];
}
export interface GiftAppDetail extends GiftApp {
  description: string | null;
  packages: GiftPackage[];
  dlc_total: number;
  zones: string[];
  zone_default: string;
}
export async function getGiftDetail(locale: string, appId: number): Promise<GiftAppDetail | null>; // server
export async function fetchGiftDlc(
  locale: string,
  appId: number,
  q: string,
  offset: number,
): Promise<GiftsList>; // client
```

**GiftPurchasePanel behaviour:**

- Props: `detail: GiftAppDetail`, `skuId: string`, `locale: string`.
- State: selected `packageId` (default: first package), selected `zone` (default `zone_default`; selector shows `zones` with «другой регион» collapsing beyond the first four), `inviteUrl` input (client-side regex mirroring Task 4's shapes, error text from i18n), guest `email` when unauthenticated (reuse the auth context exactly as `PurchasePanel` does).
- Price display: from the selected package × zone (`price_uzs` primary, `price_usd` secondary); zone with no price → option disabled with a hint.
- Buy: `POST /api/v1/orders` body `{ currency: "UZS", items: [{ sku_id: skuId, qty: 1, amount_usd: selected.price_usd, fulfillment_data: { app_id, package_id, region: zone, invite_url } }], delivery_email | guest_email }` with `Idempotency-Key`; then `POST /payments/intents` and redirect — via the extracted `lib/gift-checkout.ts`. On 422 with `expected_amount_usd` → refresh the detail (`router.refresh()` + toast «цена обновилась», re-render with the server figure). v1 scope-cuts, deliberate: no promo field, no wallet pay, no qty (always one gift).
- Timeline copy under the button: «подарок отправляется ботом, обычно до часа» + accept-the-gift explainer (i18n).
- **DlcBrowser**: rendered collapsed under the description («DLC: 423 — показать»); expanding mounts the search box + paged grid backed by `fetchGiftDlc`; each DLC row links to its own `/store/steam-gifts/{dlcAppId}` page. Never renders more than a page (24) at once.
- **OrderStatus gift card**: when a delivery artifact has `kind === "gift"` (allow-listed in Task 5), render an instruction block from `web.gifts.delivered.*` (title, steps: check Steam notifications/email, sender is a bot account — Steam shows a standard warning, accept within 30 days) instead of the generic artifact dump; show `app_name`/`package_name`.

**i18n additions**: `web.gifts.game.{edition,region,otherRegion,noPriceInRegion,inviteLabel,invitePlaceholder,inviteError,inviteGuideTitle,inviteGuideSteps,buy,timeline,accept}`, `web.gifts.delivered.{title,step1,step2,step3,sender}`, `web.gifts.priceChanged`.

- [ ] **Step 1: Tests first**: `GiftPurchasePanel.test.tsx` — default selection renders the CIS price; switching zone re-prices; bad invite URL blocks submit with the i18n error; submit POSTs the exact body above (mock `lib/gift-checkout.ts`); 422 price-change path shows the toast. `DlcBrowser.test.tsx` — collapsed by default; expand fetches page 1; search narrows (fake timers).
- [ ] **Step 2: Run — FAIL.**
- [ ] **Step 3: Implement** (`[appId]/page.tsx` breadcrumbs + `Product` JSON-LD for the single app with the default-zone price, `notFound()` on null detail).
- [ ] **Step 4: Run — PASS**; `pnpm --filter web exec tsc --noEmit`; `pnpm --filter web lint`; locale-parity check.
- [ ] **Step 5: E2E happy path on dev** (manual, flag on): open game page → pick edition/region → paste profile link → order created (mock provider) → order page shows the pending timeline. Fix what breaks.
- [ ] **Step 6: Commit**

```bash
git add apps/web/src/app/[locale]/store/steam-gifts apps/web/src/components/gifts apps/web/src/components/order/OrderStatus.tsx apps/web/src/lib/gifts.ts apps/web/src/lib/gift-checkout.ts packages/i18n/locales
git commit -m "feat(web): steam gift game page with edition/region checkout and delivery card"
```

---

### Task 10: Docs, OpenAPI/client regen, ADR

**Files:**

- Create: `docs/decisions/0066-steam-gifts-live-catalog.md` (MADR via `docs/decisions/0000-template.md`)
- Create: `docs/architecture/sequence-diagrams/steam-gift-purchase.mmd` (Mermaid: buyer → web → api(gifts proxy/orders) → G-Engine → reconcile → delivery)
- Create: `docs/product/flows/steam-gifts.md` (user-facing flow + the same diagram embedded)
- Create: `docs/runbooks/steam-gifts.md`
- Modify: `docs/architecture/module-map.md` (new `gifts` module + its edges: orders→gifts, gifts→fx, gifts→G-Engine), `docs/api/README.md` (gifts endpoints: no auth, cache behaviour, 404-when-disabled), `docs/security/pii-handling.md` (Steam profile URL / steamid64 stored in `fulfillment_data` and supplier metadata — treat like `player_id`: never logged, shown only to the buyer and admins)
- Regenerate: `docs/api/openapi.json` + `packages/api-client/src/generated/*`

**ADR-0066 content (decision points to record):** live proxy over SKU import (4 241 daily-moving prices); dynamic checkout on the Stars pattern with server re-price ±2 %; success at `shipped` not `delivered`; adopt-don't-rebuy because `/gifts/orders` takes no client uuid; margin as a DB runtime setting over env; `gift` as a third mapping kind over a parallel table.

**Runbook sections:** flag flip procedure (api env + restart, then web needs nothing — section un-404s); «gifts catalog stale» log meaning and upstream-outage behaviour; parked id-less gift tasks (`gift order not found at supplier`) — how to check G-Engine's panel and either bind the order id (admin retry after setting `external_order_id`) or refund; post-`shipped` `refunded` (recipient declined) — manual refund path; margin change (admin page, takes ≤ 1 h everywhere or flush `gifts:margin`); **ops checklist for launch**: add `steam-gifts` to `RISK_LIQUID_BRANDS` on prod (spec § 4.3 — gift games are resellable), verify G-Engine balance alert threshold covers AAA wholesale ($30–40).

- [ ] **Step 1: Write all docs.** ADR status `accepted`, date 2026-09-03.
- [ ] **Step 2: Regenerate** — `make gen-api`; commit the diff of `docs/api/openapi.json` and `packages/api-client/src/generated/`.
- [ ] **Step 3: Full local gate** — `make lint typecheck test` (all suites, both languages) and `pnpm prettier --check .` — Expected: green. Fix anything that is not.
- [ ] **Step 4: Commit**

```bash
git add docs packages/api-client
git commit -m "docs(gifts): ADR-0066, module map, flows, runbook; regenerate openapi + ts client"
```

---

## Execution notes for the controller

- Tasks 1→6 are strictly ordered (each consumes the previous one's surface). Task 7 depends only on Task 2. Tasks 8–9 depend on Task 3 (and 9 on 4+6 for the live smoke). Task 10 last.
- The feature deploys dark: nothing here flips `STEAM_GIFTS_ENABLED`, seeds prod, or touches prod env — those are operator actions listed in the runbook.
- Do not push or deploy; local commits only.
