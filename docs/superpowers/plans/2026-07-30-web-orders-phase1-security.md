# Web Orders — Phase 1 (Security) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the customer-facing API from ever sending internal/supplier data — replace the delivery-artifact blocklist with a whitelist, and remove the internal `supplier_order_id` from the customer order DTO (keeping it for admins).

**Architecture:** Two API-layer changes, no schema-shape break for deliveries (artifact stays a `dict`). `DeliveryOut.artifact` is filtered through an explicit allow-list before serialization. `OrderItemOut` (customer) drops `supplier_order_id`; a new `OrderItemAdminOut` subclass re-adds it so `OrderAdminOut` still exposes it. Frontend customer types and the OpenAPI/TS client are regenerated to match.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest + testcontainers (integration); TypeScript (web/miniapp customer types); `make gen-api` for OpenAPI + `@hey-api` client.

## Global Constraints

- **Never send supplier/internal identifiers to any frontend.** The customer delivery artifact must expose ONLY an explicit whitelist; every other key (`source`, `external_id`, `external_order_id`, `external_product_id`, `inventory_code_id`, `sku_id`, `catalogue_name`, `qty`, `amount_units`, `give_amount_units`, and anything future suppliers add) is dropped.
- **Whitelist, not blocklist** — the fix must not re-leak when a new supplier adds a field.
- Admin surfaces (`/admin/fulfillment/tasks`, `OrderAdminOut`) keep full internal data — this plan only narrows the CUSTOMER surface.
- Never disable/skip a failing test. `test_fulfillment_routes.py` currently asserts `sku_id` IS present in the customer artifact (it codifies the leak) — that assertion must be CORRECTED in the same change, not removed wholesale.
- `mypy --strict` + ruff clean (`line-length=100`); `tsc` strict clean (web + miniapp).
- OpenAPI regenerated (`make gen-api`); no `openapi-drift`.
- Docs updated in the same change (fulfillment README + security notes).

---

### Task 1: Whitelist the customer delivery artifact

**Files:**

- Modify: `apps/api/src/yupay/modules/fulfillment/routes.py:86-108` (replace `_CUSTOMER_HIDDEN_ARTIFACT_KEYS` blocklist + `_to_customer_delivery_out`)
- Modify: `apps/api/src/yupay/modules/fulfillment/README.md` (the artifact/audit note around line 43/67)
- Modify: `docs/security/pii-handling.md` (note the whitelist guarantee)
- Test (unit): `apps/api/tests/unit/test_delivery_artifact_whitelist.py` (create)
- Test (integration, correct existing leak-assertion): `apps/api/tests/integration/test_fulfillment_routes.py:189-196`

**Interfaces:**

- Consumes: `DeliveryOut` (`fulfillment/schemas.py` — `artifact: dict[str, Any]`, unchanged).
- Produces: `_CUSTOMER_SAFE_ARTIFACT_KEYS: frozenset[str]` and an updated `_to_customer_delivery_out(row) -> DeliveryOut` that keeps only whitelisted keys. No signature change — same call site (`list_order_deliveries`).

- [ ] **Step 1: Write the failing unit test**

Create `apps/api/tests/unit/test_delivery_artifact_whitelist.py`:

```python
"""The customer delivery DTO must expose ONLY whitelisted artifact keys.

Internal/supplier fields (source, external ids, sku/inventory ids, raw units)
stored on the row for audit must never reach the customer-facing API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from yupay.modules.fulfillment.routes import _to_customer_delivery_out


@dataclass
class _Row:
    id: str
    order_item_id: str
    channel: str
    artifact_kind: str
    artifact: dict[str, Any]
    delivered_at: datetime


def _row(artifact: dict[str, Any]) -> _Row:
    return _Row(
        id="d1",
        order_item_id="oi1",
        channel="in_app",
        artifact_kind="voucher_code",
        artifact=artifact,
        delivered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_supplier_internal_keys_are_stripped() -> None:
    out = _to_customer_delivery_out(
        _row(
            {
                "code": "GIFT-123",
                "source": "waxpeer",
                "external_id": "mock_x",
                "external_order_id": "wp-999",
                "external_product_id": "p-1",
                "inventory_code_id": "inv-7",
                "sku_id": "sku-abc",
                "catalogue_name": "internal-cat",
                "qty": 1,
                "amount_units": "20000",
                "give_amount_units": "500",
            }
        )
    )
    assert out.artifact == {"code": "GIFT-123"}


def test_customer_supplied_and_deliverable_keys_survive() -> None:
    out = _to_customer_delivery_out(
        _row(
            {
                "steam_login": "player42",
                "fulfillment_data": {"steam_login": "player42"},
                "key": "AAAA-BBBB",
                "message": "Enjoy!",
                "source": "waxpeer",
            }
        )
    )
    assert out.artifact == {
        "steam_login": "player42",
        "fulfillment_data": {"steam_login": "player42"},
        "key": "AAAA-BBBB",
        "message": "Enjoy!",
    }
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/api && uv run pytest tests/unit/test_delivery_artifact_whitelist.py -v`
Expected: FAIL — `test_supplier_internal_keys_are_stripped` fails because today's blocklist keeps `source`, `sku_id`, etc.

- [ ] **Step 3: Replace the blocklist with a whitelist**

In `apps/api/src/yupay/modules/fulfillment/routes.py`, replace the block at lines 86-108:

```python
# Artifact keys that ARE safe to show the customer. This is an allow-list
# (not a blocklist) on purpose: a delivery ``artifact`` also carries
# internal audit/chargeback fields — ``source`` (the upstream supplier),
# ``external_order_id``, ``inventory_code_id``, ``sku_id``,
# ``catalogue_name``, raw ``amount_units`` — that MUST NOT leave the API.
# The DB row keeps everything; admins see it via ``/admin/fulfillment``.
# A new supplier adding a field defaults to hidden until listed here.
_CUSTOMER_SAFE_ARTIFACT_KEYS: frozenset[str] = frozenset(
    {
        "code",  # single voucher/gift code
        "codes",  # multi-code delivery
        "key",  # license/activation key
        "pin",  # scratch PIN
        "serial",  # serial number
        "steam_login",  # the account the customer themselves entered
        "login",  # generic account login the customer entered
        "message",  # human-readable delivery note
        "note",  # human-readable delivery note (alt key)
        "fulfillment_data",  # the customer's own checkout input, echoed back
    }
)


def _to_customer_delivery_out(row: object) -> DeliveryOut:
    """Project a ``Delivery`` ORM row into the customer-facing DTO, keeping
    ONLY whitelisted ``artifact`` keys (everything else is internal)."""
    artifact = {
        k: v
        for k, v in (row.artifact or {}).items()  # type: ignore[attr-defined]
        if k in _CUSTOMER_SAFE_ARTIFACT_KEYS
    }
    return DeliveryOut(
        id=row.id,  # type: ignore[attr-defined]
        order_item_id=row.order_item_id,  # type: ignore[attr-defined]
        channel=row.channel,  # type: ignore[attr-defined]
        artifact_kind=row.artifact_kind,  # type: ignore[attr-defined]
        artifact=artifact,
        delivered_at=row.delivered_at,  # type: ignore[attr-defined]
    )
```

- [ ] **Step 4: Run the unit test to verify it passes**

Run: `cd apps/api && uv run pytest tests/unit/test_delivery_artifact_whitelist.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Correct the integration assertion that codified the leak**

In `apps/api/tests/integration/test_fulfillment_routes.py`, the `test_paid_order_walks_to_delivered` block currently (lines ~191-196):

```python
    assert items[0]["artifact_kind"] == "topup_receipt"
    # ``external_id`` is stored on the row for admin audit, but the
    # ... customer must not see it.
    assert "external_id" not in items[0]["artifact"]
    assert items[0]["artifact"]["sku_id"] == _seed_sku
```

Replace the last line (and tighten the comment) so it asserts the leak is CLOSED — the mock top-up artifact is `{external_id, fulfillment_data, sku_id, qty}`, of which only `fulfillment_data` is customer-safe:

```python
    assert items[0]["artifact_kind"] == "topup_receipt"
    # The delivery row stores internal audit fields (external_id, sku_id,
    # source, qty) but the customer API exposes ONLY the whitelist — here the
    # customer's own checkout input echoed back as ``fulfillment_data``.
    assert "external_id" not in items[0]["artifact"]
    assert "sku_id" not in items[0]["artifact"]
    assert "source" not in items[0]["artifact"]
    assert "qty" not in items[0]["artifact"]
    assert "fulfillment_data" in items[0]["artifact"]
```

- [ ] **Step 6: Run the fulfillment route tests**

Run: `cd apps/api && uv run pytest tests/integration/test_fulfillment_routes.py -v`
Expected: PASS. (The manual-voucher test that asserts `artifact["code"] == "MANUAL-TEST-001"` still passes — `code` is whitelisted.)

- [ ] **Step 7: Update docs (fulfillment README + PII note)**

In `apps/api/src/yupay/modules/fulfillment/README.md`, update the artifact note (near line 43/67) to state the customer API returns only whitelisted artifact keys (`code`/`codes`/`key`/`pin`/`serial`/`steam_login`/`login`/`message`/`note`/`fulfillment_data`) and that `source` and all external/internal ids are admin-only.

In `docs/security/pii-handling.md`, add a line under the deliveries/orders surface: the delivery artifact is projected through `_CUSTOMER_SAFE_ARTIFACT_KEYS` (allow-list) before it reaches any frontend; the upstream supplier (`source`) is never exposed.

- [ ] **Step 8: Lint + typecheck the API**

Run: `cd apps/api && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src`
Expected: all clean.

- [ ] **Step 9: Commit**

```bash
git add apps/api/src/yupay/modules/fulfillment/routes.py \
        apps/api/tests/unit/test_delivery_artifact_whitelist.py \
        apps/api/tests/integration/test_fulfillment_routes.py \
        apps/api/src/yupay/modules/fulfillment/README.md \
        docs/security/pii-handling.md
git commit -m "fix(api/fulfillment): whitelist customer delivery artifact keys

The customer /orders/{id}/deliveries response stripped only external_id (a
blocklist) and leaked source (upstream supplier), sku_id, inventory_code_id,
external_order_id and raw units. Replace with an allow-list so only
customer-safe keys reach the frontend; new supplier fields default to hidden.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Remove `supplier_order_id` from the customer order DTO (keep it for admin)

**Files:**

- Modify: `apps/api/src/yupay/modules/orders/schemas.py:71-83,114,123-134` (drop field from `OrderItemOut`, add `OrderItemAdminOut`, point `OrderAdminOut.items` at it)
- Modify: `apps/api/src/yupay/modules/orders/api.py` (export `OrderItemAdminOut` if the module re-exports item DTOs)
- Modify: `apps/web/src/lib/orders-types.ts:20` (remove `supplier_order_id`)
- Modify: `apps/web/src/components/order/OrderDeliveredModal.test.tsx:54` (remove the field from the fixture)
- Modify: `apps/miniapp/src/lib/orders.ts:51` (remove `supplier_order_id`)
- Regenerate: `docs/api/openapi.json` + `packages/api-client/` via `make gen-api`
- Test (integration): `apps/api/tests/integration/test_fulfillment_routes.py` OR the orders route test — add an assertion that the customer order payload has no `supplier_order_id` and the admin payload still does.

**Interfaces:**

- Consumes: existing `OrderItemOut`, `OrderAdminOut` (`orders/schemas.py`), `_to_order_out` / `_to_admin_order_out` (`orders/routes.py:41,47`).
- Produces: `OrderItemAdminOut(OrderItemOut)` with `supplier_order_id: str | None`; `OrderAdminOut.items: list[OrderItemAdminOut]`. Customer `OrderItemOut` no longer carries `supplier_order_id`.

- [ ] **Step 1: Write the failing integration assertion**

In `apps/api/tests/integration/test_fulfillment_routes.py`, inside `test_paid_order_walks_to_delivered` (after the order reaches delivered and you have the order JSON, or fetch `GET /api/v1/orders/{order_id}`), add:

```python
    order_resp = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert order_resp.status_code == 200, order_resp.text
    item0 = order_resp.json()["items"][0]
    # supplier_order_id is an internal upstream id — customers must not see it.
    assert "supplier_order_id" not in item0
```

(Use whatever auth token / owner the surrounding test already established for the order; mirror the existing `deliveries` call in the same test.)

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/api && uv run pytest tests/integration/test_fulfillment_routes.py::test_paid_order_walks_to_delivered -v`
Expected: FAIL — `supplier_order_id` is still present on the customer item.

- [ ] **Step 3: Split the DTO**

In `apps/api/src/yupay/modules/orders/schemas.py`:

Remove `supplier_order_id` from `OrderItemOut` (delete line 82). Then add, after `OrderItemOut`:

```python
class OrderItemAdminOut(OrderItemOut):
    """Admin view of an order line — adds the internal supplier order id."""

    supplier_order_id: str | None = None
```

Change `OrderAdminOut` to override `items`:

```python
class OrderAdminOut(OrderOut):
    """Same as :class:`OrderOut` but exposes actor identifiers + audit trail."""

    items: list[OrderItemAdminOut]  # type: ignore[assignment]
    user_id: str | None
    guest_email: str | None
    events: list[OrderEventOut]
```

Add `OrderItemAdminOut` to `__all__`.

- [ ] **Step 4: Export the new DTO if the module re-exports item DTOs**

If `apps/api/src/yupay/modules/orders/api.py` re-exports `OrderItemOut`, add `OrderItemAdminOut` alongside it (keep the public surface consistent).

- [ ] **Step 5: Run the API test to verify the customer item is clean and admin still has it**

Run: `cd apps/api && uv run pytest tests/integration/test_fulfillment_routes.py -v` and the orders admin test (whichever asserts admin output). Add, in an existing admin-order test, an assertion that `items[0]` DOES contain `supplier_order_id`.
Expected: PASS.

- [ ] **Step 6: Update frontend customer types**

Remove `supplier_order_id: string | null;` from `apps/web/src/lib/orders-types.ts:20` and `apps/miniapp/src/lib/orders.ts:51`. Remove the `supplier_order_id: null,` line from the fixture at `apps/web/src/components/order/OrderDeliveredModal.test.tsx:54`.

- [ ] **Step 7: Typecheck web + miniapp**

Run: `pnpm --filter @yupay/web exec tsc --noEmit && pnpm --filter @yupay/miniapp exec tsc --noEmit`
(Do NOT run a host `next build` for web — bind-mount `.next` trap. tsc only.)
Expected: clean — nothing else references `supplier_order_id` on the customer type.

- [ ] **Step 8: Regenerate OpenAPI + TS client**

Run: `make gen-api`
Then verify no unexpected drift beyond the removed field / new admin DTO: `git diff --stat docs/api/openapi.json packages/api-client`
Expected: `supplier_order_id` removed from the customer item schema; `OrderItemAdminOut` present.

- [ ] **Step 9: Lint + typecheck everything touched**

Run: `cd apps/api && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src`
Run: `pnpm --filter @yupay/web exec tsc --noEmit && pnpm --filter @yupay/miniapp exec tsc --noEmit`
Expected: all clean.

- [ ] **Step 10: Commit**

```bash
git add apps/api/src/yupay/modules/orders/schemas.py \
        apps/api/src/yupay/modules/orders/api.py \
        apps/api/tests/integration/test_fulfillment_routes.py \
        apps/web/src/lib/orders-types.ts \
        apps/web/src/components/order/OrderDeliveredModal.test.tsx \
        apps/miniapp/src/lib/orders.ts \
        docs/api/openapi.json packages/api-client
git commit -m "fix(api/orders): drop supplier_order_id from customer order DTO

supplier_order_id is an internal upstream supplier id that was serialized on
every customer order line. Move it to an admin-only OrderItemAdminOut so
OrderAdminOut still exposes it while the customer surface no longer does.
Regenerate OpenAPI + TS client; drop the field from web/miniapp customer types.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

- **Spec coverage:** Phase 1 of the spec = (a) artifact blocklist → whitelist in `_to_customer_delivery_out` ✅ Task 1; (b) drop `supplier_order_id` from customer `OrderItemOut`, keep for admin ✅ Task 2; (c) backend test that a waxpeer-style artifact is stripped ✅ Task 1 Step 1 + corrected integration assertion; (d) customer item has no `supplier_order_id` ✅ Task 2 Step 1. The spec noted the web `ArtifactReveal` / miniapp `ArtifactBlock` dumps are "folded into Phase 2" — correctly deferred here (they're safe now because the data is gone at the API).
- **Placeholder scan:** none — every step has concrete code/commands.
- **Type consistency:** `_CUSTOMER_SAFE_ARTIFACT_KEYS` used in Task 1; `OrderItemAdminOut` defined in Task 2 Step 3 and referenced by `OrderAdminOut.items` in the same step; frontend field name `supplier_order_id` matches across web/miniapp/openapi.
- **Note for executor:** `OrderAdminOut.items` override needs `# type: ignore[assignment]` (narrowing a base `list[OrderItemOut]` to `list[OrderItemAdminOut]`); mypy Step 9 confirms nothing else breaks. Since `OrderItemAdminOut` is a subclass, `model_validate` on the ORM order still populates `supplier_order_id` from the item attribute — no service-layer change needed.
