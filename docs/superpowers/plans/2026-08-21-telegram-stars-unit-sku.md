# Telegram Stars as a unit SKU — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sell Telegram Stars as one SKU priced per star (`qty` = star count), with the package grid built on the storefront from that rate.

**Architecture:** Additive `min_qty`/`max_qty` on `skus`, dual-read in checkout and G-Engine so old variable Stars and new unit Stars coexist until an **idempotent seed** (not Alembic) flips `tg-stars-any` and deactivates packs. The wire `qty` ceiling rises to 50_000 only for unit SKUs; every other product stays capped at 100.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, pytest; Next.js (web), Vite React (miniapp), admin SPA.

**Spec:** `docs/superpowers/specs/2026-08-21-telegram-stars-unit-sku-design.md`

## Global Constraints

- Steam `variable_amount` path does not change. Tests that price Steam must still pass unchanged.
- Money is `Decimal` server-side, never float. The client never sends a price.
- Do not log PII (Telegram user id, email, username in fulfillment_data).
- All three locales for any new user-facing string.
- `ruff check`, `ruff format --check`, `mypy apps`, `prettier --check .` before every commit.
- Supplier-adapter coverage stays ≥95% (`gengine` fulfiller).
- **Alembic must not rewrite Stars rows.** Schema only. Data change is a separate idempotent seed run after the new code is live.
- **Do not delete SKU rows.** Packs are `active=false` only.

---

## Production rollout (read before Task 1)

This is a live catalog product. A flag-day “flip the SKU and deploy together” will 422 every Stars checkout for the gap between the two.

```
1. Deploy code + migration 0049 (columns nullable, all existing rows NULL).
   Storefront still sees variable Stars + packs. New code dual-reads:
   unit SKU (min_qty set) → qty path; variable → old path.
2. Confirm /store/telegram-stars still sells (packs + free amount) on prod.
3. Run the seed (Task 10) against prod:
   - abort if cost_usdt on tg-stars-any is not per-star (guard in the script);
   - set variable_amount=false, min_qty/max_qty, amount_unit=Stars,
     units_per_usd=NULL, mapping.quantity=1;
   - active=false on the other telegram-stars SKUs.
4. Confirm one test purchase: tile 50 and typed 50 both create ONE G-Engine
   order with Quantity=50.
5. Rollback (if needed): re-run seed with --revert (reactivates packs,
   restores variable_amount). Code rollback is the previous image; migration
   0049 downgrade drops the new columns (safe: seed already NULLed them
   on revert, and no other product uses them).
```

**Do not** put step 3 in `upgrade()`. A failed deploy must not leave Stars with packs off and code that still expects them.

**In-flight orders.** A pack SKU paid but not yet fulfilled: `qty=1`, `mapping.quantity=N`. After Task 4, Quantity = `1 * N` = N. A new unit-SKU order: `qty=N`, `mapping.quantity=1` → N. Historical `order_items` are not rewritten.

---

### Task 1: Schema — `min_qty` / `max_qty` and relax `amount_unit` CHECK

**Why this is a prod risk:** `ck_skus_amount_unit_complete` (migration 0047) requires `amount_unit` and `units_per_usd` together. The unit SKU needs `amount_unit='Stars'` with `units_per_usd` NULL. Shipping the seed without relaxing this CHECK will IntegrityError in prod and leave the catalog half-flipped.

**Files:**

- Create: `apps/api/migrations/versions/0049_sku_min_max_qty.py`
- Modify: `apps/api/src/yupay/modules/catalog/models.py` (`Sku` columns + `__table_args__`)
- Test: `apps/api/tests/integration/test_catalog_variable_sku.py` (add CHECK cases; do not rename the file)

**Interfaces:**

- Consumes: nothing.
- Produces: `Sku.min_qty: int | None`, `Sku.max_qty: int | None`. CHECK `ck_skus_qty_bounds_complete`: both NULL, or both set with `min_qty >= 1 AND max_qty >= min_qty`. CHECK `ck_skus_amount_unit_complete` replaced with: (both unit fields NULL) OR (both set and `units_per_usd > 0`) OR (`amount_unit` set AND `units_per_usd` NULL AND `min_qty` IS NOT NULL).

- [ ] **Step 1: Write the failing CHECK tests**

In `apps/api/tests/integration/test_catalog_variable_sku.py`, add (reuse the existing category/brand/product fixtures in that file):

```python
async def test_qty_bounds_must_arrive_together(db_session: AsyncSession, _sku: Sku) -> None:
    _sku.min_qty = 50
    _sku.max_qty = None
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_qty_bounds_accept_a_closed_star_range(db_session: AsyncSession, _sku: Sku) -> None:
    _sku.min_qty = 50
    _sku.max_qty = 2500
    await db_session.flush()
    await db_session.refresh(_sku)
    assert _sku.min_qty == 50
    assert _sku.max_qty == 2500


async def test_amount_unit_may_stand_alone_when_qty_bounds_are_set(
    db_session: AsyncSession, _sku: Sku
) -> None:
    _sku.amount_unit = "Stars"
    _sku.units_per_usd = None
    _sku.min_qty = 50
    _sku.max_qty = 2500
    await db_session.flush()
```

- [ ] **Step 2: Run tests, expect fail**

Run: `uv run pytest apps/api/tests/integration/test_catalog_variable_sku.py -k qty_bounds -v`

Expected: FAIL — columns don't exist / CHECK not there.

- [ ] **Step 3: Migration**

`0048_sku_units` is the current head. New file `0049_sku_min_max_qty.py`:

```python
"""Allow a SKU to be sold by integer qty (Telegram Stars: one star = qty 1).

Revision ID: 0049_sku_min_max_qty
Revises: 0048_sku_units
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0049_sku_min_max_qty"
down_revision: str | None = "0048_sku_units"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("skus", sa.Column("min_qty", sa.Integer(), nullable=True))
    op.add_column("skus", sa.Column("max_qty", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_skus_qty_bounds_complete",
        "skus",
        "(min_qty IS NULL AND max_qty IS NULL) OR "
        "(min_qty IS NOT NULL AND max_qty IS NOT NULL "
        "AND min_qty >= 1 AND max_qty >= min_qty)",
    )
    op.drop_constraint("ck_skus_amount_unit_complete", "skus", type_="check")
    op.create_check_constraint(
        "ck_skus_amount_unit_complete",
        "skus",
        "(amount_unit IS NULL AND units_per_usd IS NULL) "
        "OR (amount_unit IS NOT NULL AND units_per_usd IS NOT NULL AND units_per_usd > 0) "
        "OR (amount_unit IS NOT NULL AND units_per_usd IS NULL AND min_qty IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_skus_amount_unit_complete", "skus", type_="check")
    op.create_check_constraint(
        "ck_skus_amount_unit_complete",
        "skus",
        "(amount_unit IS NULL AND units_per_usd IS NULL) "
        "OR (amount_unit IS NOT NULL AND units_per_usd IS NOT NULL AND units_per_usd > 0)",
    )
    op.drop_constraint("ck_skus_qty_bounds_complete", "skus", type_="check")
    op.drop_column("skus", "max_qty")
    op.drop_column("skus", "min_qty")
```

**Downgrade is unsafe if a unit SKU row exists** (`amount_unit` set, `units_per_usd` NULL). The revert seed (Task 10) must run first. Document that in the migration docstring.

On `Sku` in `models.py`, next to `units`:

```python
    min_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

Add the two CHECKs to `__table_args__` (SQLAlchemy should match Alembic). Existing rows stay NULL — Steam, packs, gift cards unchanged.

- [ ] **Step 4: Run tests, expect pass**

Run: `uv run pytest apps/api/tests/integration/test_catalog_variable_sku.py -k "qty_bounds or amount_unit_may" -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/migrations/versions/0049_sku_min_max_qty.py \
  apps/api/src/yupay/modules/catalog/models.py \
  apps/api/tests/integration/test_catalog_variable_sku.py
git commit -m "feat(catalog): min_qty/max_qty bounds for unit SKUs"
```

---

### Task 2: `is_unit_sku` + public/admin DTOs

**Files:**

- Create: `apps/api/src/yupay/modules/catalog/unit_sku.py`
- Create: `apps/api/tests/unit/test_unit_sku.py`
- Modify: `apps/api/src/yupay/modules/catalog/schemas.py` (`SkuOut`)
- Modify: `apps/api/src/yupay/modules/catalog/admin_schemas.py` (`SkuCreate`, `SkuUpdate`, `AdminSkuOut`, validators)
- Modify: `apps/api/src/yupay/modules/catalog/admin_service.py` (`create_sku`, `update_sku`, `_to_admin_sku`, `_apply_amount_unit`)
- Modify: `apps/api/src/yupay/modules/catalog/service.py` (both `SkuOut(...)` constructors)

**Interfaces:**

- Consumes: `Sku.min_qty` / `Sku.max_qty` from Task 1.
- Produces:
  - `is_unit_sku(sku: Sku) -> bool` — `not variable_amount` and `amount_unit` and `min_qty` and `max_qty` all set.
  - `DEFAULT_QTY_MAX: int = 100`
  - `UNIT_QTY_WIRE_MAX: int = 50_000`
  - `SkuOut.min_qty: int | None`, `SkuOut.max_qty: int | None` (optional, default None — old clients ignore).

- [ ] **Step 1: Failing unit tests**

```python
# apps/api/tests/unit/test_unit_sku.py
from types import SimpleNamespace

from yupay.modules.catalog.unit_sku import is_unit_sku


def test_stars_with_qty_bounds_is_a_unit_sku() -> None:
    sku = SimpleNamespace(
        variable_amount=False, amount_unit="Stars", min_qty=50, max_qty=2500
    )
    assert is_unit_sku(sku) is True


def test_steam_variable_is_not_a_unit_sku() -> None:
    sku = SimpleNamespace(
        variable_amount=True, amount_unit=None, min_qty=None, max_qty=None
    )
    assert is_unit_sku(sku) is False


def test_a_pack_without_bounds_is_not_a_unit_sku() -> None:
    sku = SimpleNamespace(
        variable_amount=False, amount_unit="Stars", min_qty=None, max_qty=None
    )
    assert is_unit_sku(sku) is False
```

- [ ] **Step 2: Run, expect fail**

Run: `uv run pytest apps/api/tests/unit/test_unit_sku.py -v`

Expected: FAIL — module missing.

- [ ] **Step 3: Implement helper + DTO fields**

`unit_sku.py`:

```python
DEFAULT_QTY_MAX = 100
UNIT_QTY_WIRE_MAX = 50_000


def is_unit_sku(sku: object) -> bool:
    """Sold as integer qty of a named unit (Telegram Stars), not Steam dollars."""
    if getattr(sku, "variable_amount", False):
        return False
    return (
        getattr(sku, "amount_unit", None) is not None
        and getattr(sku, "min_qty", None) is not None
        and getattr(sku, "max_qty", None) is not None
    )
```

Add `min_qty` / `max_qty` to `SkuOut`, `SkuCreate`, `SkuUpdate`, `AdminSkuOut`. Mirror `require_variable_amount_fields` with `require_qty_bounds` (both or neither; min>=1; max>=min). Call it from SkuCreate/SkuUpdate validators and from `update_sku` on the merged row.

Relax `_apply_amount_unit`: if `min_qty` is set, `units_per_usd` may be NULL. If `min_qty` is NULL, keep the old “both or neither” rule for `amount_unit`/`units_per_usd`.

Pass `min_qty=sku.min_qty`, `max_qty=sku.max_qty` in both `SkuOut(...)` sites in `catalog/service.py` (~lines 491 and 551).

- [ ] **Step 4: Run tests**

Run: `uv run pytest apps/api/tests/unit/test_unit_sku.py apps/api/tests/integration/test_admin_skus.py -v`

Expected: PASS (add an admin round-trip in `test_admin_skus.py` if that file exists; otherwise a small integration test that POST/PATCH min_qty/max_qty).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/yupay/modules/catalog/unit_sku.py \
  apps/api/tests/unit/test_unit_sku.py \
  apps/api/src/yupay/modules/catalog/schemas.py \
  apps/api/src/yupay/modules/catalog/admin_schemas.py \
  apps/api/src/yupay/modules/catalog/admin_service.py \
  apps/api/src/yupay/modules/catalog/service.py
git commit -m "feat(catalog): expose unit-SKU qty bounds on admin and storefront"
```

---

### Task 3: Checkout — qty gate (security)

**This is the fraud control.** Raising `OrderItemIn.qty` to 50_000 without a second gate lets a client buy `qty=50000` of UC / a gift card. The wire max is 50_000; the **real** max is SKU `max_qty` for unit SKUs and `DEFAULT_QTY_MAX` (100) for everyone else.

**Files:**

- Modify: `apps/api/src/yupay/modules/orders/schemas.py` (`qty: Field(ge=1, le=UNIT_QTY_WIRE_MAX)`)
- Modify: `apps/api/src/yupay/modules/orders/service.py` (`_resolve_line_unit_price`)
- Modify: `apps/api/src/yupay/modules/catalog/unit_sku.py` — add `assert_qty_allowed(sku, qty) -> None` raising `ValidationError`
- Test: `apps/api/tests/integration/test_checkout_variable_amount.py` (Steam still qty=1) + new `apps/api/tests/integration/test_checkout_unit_sku.py`

**Interfaces:**

- Consumes: `is_unit_sku`, `DEFAULT_QTY_MAX`, `UNIT_QTY_WIRE_MAX`.
- Produces: `_resolve_line_unit_price` returns `sku.price_usd` for a unit SKU (fixed-price path). `amount_usd` on a unit SKU → 422. `qty` outside `[min_qty, max_qty]` → 422. Non-unit `qty > 100` → 422.

- [ ] **Step 1: Failing tests**

```python
# test_checkout_unit_sku.py — build product+unit SKU (variable_amount=False,
# amount_unit="Stars", min_qty=50, max_qty=2500, price_usd=Decimal("0.02"),
# optional UZS override "250.00") the same way test_checkout_variable_amount
# builds Steam.

async def test_qty_500_charges_500_times_the_star_price(client, ...):
    r = await client.post("/api/v1/orders", json={
        "currency": "UZS",
        "items": [{"sku_id": sku_id, "qty": 500, "fulfillment_data": {"username": "durov"}}],
        "guest_email": "buyer@example.com",
    }, headers={"Idempotency-Key": str(uuid4())})
    assert r.status_code == 201
    body = r.json()
    assert body["items"][0]["qty"] == 500
    # override 250 UZS × 500
    assert Decimal(body["total_charged"]) == Decimal("125000")


async def test_qty_below_min_is_422(client, ...):
    r = await client.post(..., json={"items": [{"sku_id": sku_id, "qty": 49, ...}]})
    assert r.status_code == 422


async def test_qty_above_max_is_422(client, ...):
    r = await client.post(..., json={"items": [{"sku_id": sku_id, "qty": 2501, ...}]})
    assert r.status_code == 422


async def test_amount_usd_on_a_unit_sku_is_422(client, ...):
    r = await client.post(..., json={"items": [{"sku_id": sku_id, "qty": 50, "amount_usd": "1"}]})
    assert r.status_code == 422


async def test_a_fixed_gift_card_still_rejects_qty_over_100(client, ...):
    """Security: the raised wire max must not apply to ordinary SKUs."""
    r = await client.post(..., json={"items": [{"sku_id": gift_sku_id, "qty": 101}]})
    assert r.status_code == 422


async def test_usd_sale_of_stars_is_allowed(client, ...):
    r = await client.post(..., json={"currency": "USD", "items": [{"sku_id": sku_id, "qty": 50}]})
    assert r.status_code == 201
    assert Decimal(r.json()["total_charged"]) == Decimal("1.00")  # 50 × 0.02
```

Keep an existing Steam test that `qty=2` on a variable SKU is 422.

- [ ] **Step 2: Run, expect fail**

Run: `uv run pytest apps/api/tests/integration/test_checkout_unit_sku.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement the gate**

`unit_sku.py`:

```python
from yupay.core.errors import ValidationError

def assert_qty_allowed(sku: object, qty: int) -> None:
    if is_unit_sku(sku):
        lo = int(getattr(sku, "min_qty"))
        hi = int(getattr(sku, "max_qty"))
        if qty < lo or qty > hi:
            raise ValidationError(
                "quantity is outside the allowed range",
                extra={"min_qty": lo, "max_qty": hi, "qty": qty},
            )
        return
    if qty > DEFAULT_QTY_MAX:
        raise ValidationError(
            "quantity exceeds the maximum for this product",
            extra={"max_qty": DEFAULT_QTY_MAX, "qty": qty},
        )
```

In `_resolve_line_unit_price`, **before** the `variable_amount` branch:

```python
assert_qty_allowed(sku, line.qty)
```

`OrderItemIn.qty`: `Field(ge=1, le=UNIT_QTY_WIRE_MAX)` — import the constant from `unit_sku` (orders → catalog is an existing direction; catalog already used from orders).

A unit SKU is not `variable_amount`, so it already takes the fixed-price return `sku.price_usd` and `_compute_total_charged` already does `override.price * line.qty` / `price_usd * line.qty * rate`. Do not add a third pricing branch.

- [ ] **Step 4: Run tests**

Run: `uv run pytest apps/api/tests/integration/test_checkout_unit_sku.py apps/api/tests/integration/test_checkout_variable_amount.py -v`

Expected: PASS. Steam file unchanged in behaviour.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/yupay/modules/catalog/unit_sku.py \
  apps/api/src/yupay/modules/orders/schemas.py \
  apps/api/src/yupay/modules/orders/service.py \
  apps/api/tests/integration/test_checkout_unit_sku.py
git commit -m "feat(orders): sell unit SKUs by qty, keep qty<=100 on everything else"
```

---

### Task 4: G-Engine Quantity — dual-read (do not buy 500 top-ups)

**Files:**

- Modify: `apps/api/src/yupay/modules/fulfillment/suppliers/gengine.py` (`_quantity_for`)
- Modify: `apps/api/tests/unit/test_gengine_fulfiller.py` (`test_an_unfixed_service_is_sent_the_quantity_it_requires` and a new test)

**Interfaces:**

- Consumes: `is_unit_sku`, `OrderItem.qty`, `mapping.quantity`.
- Produces: for unfixed mappings, `Quantity = str(item.qty * mapping.quantity)` except the **legacy** variable+`units_per_usd` reverse-engineer path stays until the seed runs.

- [ ] **Step 1: Failing tests**

Keep the existing pack test (`mapping.quantity=250`, item.qty defaults to 1) asserting `Quantity=250`. Add:

```python
async def test_an_unfixed_unit_sku_sends_item_qty(monkeypatch):
    class Mapping:
        kind = "game"
        external_product_id = "72"
        external_variant_id = None
        quantity = 1

    class Item:
        sku_id = "sku-stars"
        qty = 500
        fulfillment_data = {"username": "durov"}
        unit_price_usd = Decimal("0.02")

    # _quantity_for loads the Sku — stub the SKU as a unit SKU
    # (variable_amount=False, amount_unit="Stars", min_qty=50, max_qty=2500)

    sent = await _sent_params(monkeypatch, mapping=Mapping(), item=Item())
    assert sent["params"]["Quantity"] == "500"
    assert sent.call_count == 1  # one create, not 500
```

If `_sent_params` doesn't take `item`, extend it. Pin `create_recharge_order` called once.

Also: existing variable-Stars reverse-engineer test must still pass (dual-read). If none exists, add one: `variable_amount=True`, `units_per_usd=64.7`, `qty=1`, `unit_price_usd` such that stars ≈ 250, expect Quantity=250.

- [ ] **Step 2: Run, expect fail**

Run: `uv run pytest apps/api/tests/unit/test_gengine_fulfiller.py -k unfixed -v`

Expected: FAIL on the unit-SKU test (`Quantity` still `mapping.quantity`).

- [ ] **Step 3: Implement**

Replace `_quantity_for` with:

```python
async def _quantity_for(db: AsyncSession, *, item: OrderItem, mapping: Any) -> int:
    from sqlalchemy import select
    from yupay.modules.catalog.models import Sku
    from yupay.modules.catalog.unit_sku import is_unit_sku

    sku = (await db.execute(select(Sku).where(Sku.id == item.sku_id))).scalar_one_or_none()
    if sku is not None and sku.variable_amount and sku.units_per_usd:
        units = (item.unit_price_usd * sku.units_per_usd).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        if units > 0:
            return int(units)
        raise FulfillerError(
            f"variable amount {item.unit_price_usd} resolves to no units — refusing to order"
        )
    qty = int(item.qty) * int(mapping.quantity)
    if qty <= 0:
        raise FulfillerError("quantity resolves to zero — refusing to order")
    return qty
```

Fulfillment still creates **one** `FulfillmentTask` per `OrderItem`. `qty=500` must not loop.

- [ ] **Step 4: Run tests**

Run: `uv run pytest apps/api/tests/unit/test_gengine_fulfiller.py -v`

Expected: PASS. Adapter coverage still ≥95%.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/yupay/modules/fulfillment/suppliers/gengine.py \
  apps/api/tests/unit/test_gengine_fulfiller.py
git commit -m "fix(fulfillment): G-Engine unfixed Quantity is qty × mapping"
```

---

### Task 5: Order display — `{qty} {amount_unit}`

**Files:**

- Modify: `apps/api/src/yupay/modules/orders/service.py` (`build_item_display`)
- Test: `apps/api/tests/unit/test_order_display.py` (create if missing; otherwise extend the file that already tests `build_item_display`)

**Interfaces:**

- Consumes: `is_unit_sku`, `item.qty`, `sku.amount_unit`.
- Produces: `OrderItemDisplay.denomination == "500 Stars"` for a unit SKU; `variable_amount` stays False.

- [ ] **Step 1: Failing test**

```python
def test_unit_sku_denomination_is_qty_and_unit() -> None:
    item = ...  # qty=500, sku.amount_unit="Stars", variable_amount=False, min_qty=50, max_qty=2500
    display = build_item_display(item)
    assert display.denomination == "500 Stars"
    assert display.variable_amount is False
```

Steam / pack SKUs keep `sku.denomination` unchanged.

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement**

In `build_item_display`:

```python
from yupay.modules.catalog.unit_sku import is_unit_sku

denomination = sku.denomination
if is_unit_sku(sku) and sku.amount_unit:
    denomination = f"{item.qty} {sku.amount_unit}"
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(orders): show unit-SKU lines as '{qty} Stars'"
```

---

### Task 6: Admin SKU form — min/max stars

**Files:**

- Modify: `apps/admin/src/features/catalog/skus/SkuEditPage.tsx`
- Modify: `apps/admin/src/features/catalog/types.ts` (Sku type)
- Test: existing SkuEditPage test if present; otherwise a small form-schema test

**Interfaces:**

- Consumes: `AdminSkuOut.min_qty` / `max_qty`.
- Produces: PATCH body may include `min_qty`, `max_qty`. When `amount_unit` is set and `variable_amount` is off, show “Мин. звёзд / Макс. звёзд” instead of Steam dollar bounds.

- [ ] **Step 1: Add fields to the zod schema** as optional integers, superRefine: both empty or both integers with min>=1 and max>=min.

- [ ] **Step 2: Render two inputs** next to the cost/margin block, visible when `variable_amount` is false. Labels in Russian (admin is RU-only). Empty = NULL (not a unit SKU).

- [ ] **Step 3: Manual check in browser** against local API after Task 2: open `tg-stars-any`, save 50/2500, reload.

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(admin): edit min/max qty on a unit SKU"
```

---

### Task 7: Storefront — package constant + web PurchasePanel

Miniapp does not depend on `@yupay/utils`. Duplicate the constant in both apps (same precedent as `variable-amount.ts`). Comment at the top of each file: keep the other copy in sync.

**Files:**

- Create: `apps/web/src/lib/star-packages.ts`
- Create: `apps/web/src/lib/star-packages.test.ts`
- Modify: `apps/web/src/lib/catalog.ts` (`Sku` type: optional `min_qty`/`max_qty`)
- Modify: `apps/web/src/components/store/PurchasePanel.tsx`
- Modify: `apps/web/src/components/store/PurchasePanel.test.tsx`

**Interfaces:**

- Consumes: `SkuOut.min_qty`, `max_qty`, `amount_unit`, `display_price`; `is_unit_sku` equivalent on the client: `!variable_amount && amount_unit && min_qty != null && max_qty != null`.
- Produces: `STAR_PACKAGES = [50, 75, 100, 150, 250, 350, 500, 750, 1000, 1500, 2500] as const`. `visibleStarPackages(min, max) -> number[]`. Checkout `{ sku_id, qty: N }` with **no** `amount_usd`.

Working list is in the spec; do not invent others. Final list is a one-line edit of `STAR_PACKAGES` before release.

- [ ] **Step 1: Failing tests**

```python
# star-packages.test.ts (vitest)
import { STAR_PACKAGES, visibleStarPackages, packagePrice } from "./star-packages";

test("hides packs outside admin bounds", () => {
  expect(visibleStarPackages(100, 1000)).toEqual([100, 150, 250, 350, 500, 750, 1000]);
});

test("prices a pack as N times the per-star display price", () => {
  expect(packagePrice(500, 250)).toBe(125000);
});
```

PurchasePanel test: a product with one unit SKU (no pack SKUs) still renders 50 Stars / 75 Stars tiles priced from `display_price`; clicking 50 submits `qty: 50` not `amount_usd`.

- [ ] **Step 2: Run, expect fail**

Run: `pnpm --filter @yupay/web exec vitest run src/lib/star-packages.test.ts src/components/store/PurchasePanel.test.tsx`

- [ ] **Step 3: Implement**

When the selected product has a unit SKU:

- Do **not** split `variableSku` vs `fixedSkus` for Stars packs (there are no pack SKUs).
- Render the existing amount field as a **whole number of stars** using `min_qty`/`max_qty` (reuse `unitAmountError`, drop `toUsd` / `unitsPerUsd` for this SKU).
- Render tiles from `visibleStarPackages(min_qty, max_qty)`; each tile `onClick` sets qty N on that sku id.
- `canPay` uses `qty` in range, not `amount_usd`.

Steam (`variable_amount && !min_qty`) stays on `VariableAmountCard`. A mixed product that is only Steam is unchanged.

Leave `tierPrice` in `variable-amount.ts` — Steam does not use it; after packs are gone nothing calls it from PurchasePanel. Do not delete it in this task (Mini App still might until Task 8). After Task 8, if zero callers, delete both copies and `tier-price.test.ts` in the same commit as Task 8.

- [ ] **Step 4: Run tests, expect pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(web): build Stars packs from the unit-SKU rate"
```

---

### Task 8: Mini App TopUp — same packs, same checkout

**Files:**

- Create: `apps/miniapp/src/lib/star-packages.ts` (copy of the web file)
- Create: `apps/miniapp/src/lib/star-packages.test.ts`
- Modify: `apps/miniapp/src/lib/catalog.ts` (`Package.minQty` / `maxQty` from API)
- Modify: `apps/miniapp/src/pages/TopUp.tsx`
- Modify: `apps/miniapp/src/lib/orders.ts` (checkout body `qty`, no `amount_usd` for unit SKUs)

**Interfaces:** same as Task 7.

- [ ] **Step 1: Failing tests** for `visibleStarPackages` / checkout payload (if TopUp tests exist, extend; otherwise unit-test a small helper `checkoutLine(pkg, stars) -> { sku_id, qty }`).

- [ ] **Step 2: Implement**

`skuToPackage` maps `min_qty`/`max_qty`. When `!variableAmount && amountUnit && minQty`, TopUp:

- builds tiles from the constant, filtered;
- field is integer stars;
- review/pay sends `{ sku_id, qty }` not `amount_usd`.

Remove Stars-specific `tierPrice(...)` call (~line 547). Delete `tierPrice` from both `variable-amount.ts` copies and both `tier-price.test.ts` if unused.

- [ ] **Step 3: Run**

`pnpm --filter @yupay/miniapp exec vitest run src/lib/star-packages.test.ts`

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(miniapp): build Stars packs from the unit-SKU rate"
```

---

### Task 9: ADR-0054

**Files:**

- Create: `docs/decisions/0054-telegram-stars-unit-sku.md` (MADR from `docs/decisions/0000-template.md`)
- Modify: spec status line to “Accepted, implemented”
- Amend spec Catalog section: `amount_unit` may be set without `units_per_usd` when `min_qty` is set (Task 1 CHECK).

ADR must record: why qty (not `amount_usd`); why Alembic is schema-only; why `DEFAULT_QTY_MAX=100` remains for non-unit SKUs; G-Engine `Quantity = qty × mapping.quantity`; dual-read until seed.

- [ ] **Step 1: Write ADR**

- [ ] **Step 2: Prettier**

`pnpm exec prettier --write docs/decisions/0054-telegram-stars-unit-sku.md docs/superpowers/specs/2026-08-21-telegram-stars-unit-sku-design.md`

- [ ] **Step 3: Commit**

```bash
git commit -m "docs(decisions): ADR-0054 Telegram Stars as a unit SKU"
```

---

### Task 10: Idempotent seed + runbook (the only prod data change)

**Files:**

- Create: `scripts/seed/2026-08-21_telegram_stars_unit_sku.py`
- Create: `docs/runbooks/telegram-stars-unit-sku.md`

**Interfaces:**

- Consumes: live `tg-stars-any` row + G-Engine service 72 (optional, for the cost guard).
- Produces: converted unit SKU; packs `active=false`; `--revert` undoes data (not schema).

**Cost guard (do not skip):** if `tg-stars-any.cost_usdt` is `None` or `> 0.5` (pack-sized, not per-star) or `< 0.001`, **exit 1** and print the row. An operator must look. Never silently divide by 50. If cost already looks per-star (~0.01–0.03 USDT), keep it; only set `price_usd` from `cost × (1 + margin/100)` when `margin_percent` is set, same as hourly refresh.

**qty mapping guard:** the G-Engine mapping for `tg-stars-any` must end with `quantity=1`. If it is currently 50/500, the script sets it to 1 **after** printing old → new. Getting this wrong with Task 4 live sends `Quantity = 500 * 500`.

- [ ] **Step 1: Script**

Idempotent, argparse `--revert`. Forward path:

1. Load product `telegram-stars`. Exit if missing.
2. Load `tg-stars-any`. Run cost + mapping guards.
3. `variable_amount=False`, `min_amount_usd=None`, `max_amount_usd=None`, `rate_multiplier=None`, `units_per_usd=None`, `units=None`, `amount_unit='Stars'`, `min_qty=50`, `max_qty=2500`, `active=True`.
4. Mapping: `quantity=1`, `external_variant_id=None`, service 72, `is_active=True`.
5. `UPDATE skus SET active=false WHERE product_id=... AND sku_code <> 'tg-stars-any'`.
6. Commit. Print a table of before/after.

Revert path: restore `variable_amount=True` and the previous amount-unit pair **from values the script printed / a `--from-backup` is too heavy** — store the previous pack `sku_code`s it deactivated and set `active=true`; set `tg-stars-any.variable_amount=True` with `units_per_usd` taken from a CLI flag defaulting to the G-Engine rate if available. Document that revert is “packs on, unit SKU variable again”, not a row-level time machine.

- [ ] **Step 2: Runbook** (`docs/runbooks/telegram-stars-unit-sku.md`)

Include the five-step rollout from the top of this plan, the exact `docker compose ... python` command, the cost-guard meaning, how to verify `GET /api/v1/catalog/brands/telegram-stars` returns **one** SKU, and “do not run this against prod until the image with Tasks 1–8 is live”.

- [ ] **Step 3: Dry-run on local docker** (`make migrate` then the seed). Confirm storefront shows packs-from-rate. Buy 50★ in miniapp/web against mock/G-Engine sandbox if keys exist.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(catalog): seed Telegram Stars onto a single unit SKU"
```

---

## Spec coverage

| Spec section                                              | Task                     |
| --------------------------------------------------------- | ------------------------ |
| Catalog columns, CHECK, amount_unit without units_per_usd | 1, 2                     |
| Checkout qty, 422 bounds, no amount_usd, USD allowed      | 3                        |
| qty≤100 on non-unit SKUs (security, implied by wire-max)  | 3                        |
| G-Engine Quantity, one create                             | 4                        |
| Storefront packs + field                                  | 7, 8                     |
| Admin min/max                                             | 6                        |
| Display `{qty} Stars`                                     | 5                        |
| Seed deactivate packs, no order rewrite                   | 10                       |
| ADR-0054                                                  | 9                        |
| Dual-read / deploy order                                  | rollout section + 4 + 10 |
| Steam unchanged                                           | 3 (existing tests)       |

## Placeholder scan

No TBD remaining except the operator-supplied **final** `STAR_PACKAGES` list, which the spec already defers to a one-line constant edit before release.
