# NOVA Supplier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate NOVA (nova-gifts.com) as a reserve supplier for game top-ups and as a fallback for the player check, on branch `feat/nova-supplier`.

**Architecture:** A transport-only `NovaClient` under `fulfillment/suppliers/`, a `NovaFulfiller` registered as `nova` and driven by `sku_supplier_mapping` rows, a 60-second reconcile job in the scheduler, and a separate `player_check_nova.py` module that the existing brand-scoped check consults **only** when its primary answered `error`. NOVA never becomes a primary route on its own: sourcing keeps the incumbent, and switching is an admin `force_supplier` action.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, httpx, pytest + respx, APScheduler; React 19 + TS for the admin supplier list.

**Spec:** `docs/superpowers/specs/2026-09-17-nova-supplier-design.md`

## Global Constraints

- **The fallback player check may answer `valid` or `error`. It must never answer `invalid`.** Not for a negative verdict, not for a region mismatch, not for `can_refill: false`. Only `invalid` blocks Pay (ADR-0031) and no fallback verdict may be the sole basis for that.
- **The fallback fires only when the primary answered `error`.** `valid` and `invalid` are returned untouched and NOVA is not called.
- **Validate ids and top-up ids are different namespaces.** `mobile_legends` validates; `mobile_legends_global` / `mobile_legends_ru` sell. Never pass one where the other belongs.
- **An unrecognised order status is `in_progress`**, never `succeeded` and never `failed`.
- **Money outcomes are mandatory and graded per exit** (spec §4.2). NOVA charges on create, so a create that failed on or after the call is `MoneyOutcome.UNKNOWN`, never `RETURNED`.
- **Never log the API key, a `player_id`, a `steam_login` or a customer nickname.** Player identifiers are hashed with `hash_short` exactly as `player_check.py` does today.
- `ruff` line-length 100, `mypy --strict`, Google docstrings on every public function. Supplier adapters carry a ≥95 % coverage gate (AGENTS.md §8).
- Python files: soft limit 400 LOC. `player_check.py` is already 506 — **do not add to it beyond the small dispatch hooks named in Task 5.**
- Every task ends green on `make lint typecheck` for the files it touched and on its own tests. **Run `mypy` from the repo root** (`uv run mypy apps/api/src/...`): invoked from `apps/api` it resolves `yupay.core.logging` as untyped and reports import errors on files that are already clean, which cost Task 1 a round of confusion.
- No pushing, no deploying, no prod database writes. The branch is `feat/nova-supplier`.

---

## File Structure

| File                                                              | Responsibility                                                |
| ----------------------------------------------------------------- | ------------------------------------------------------------- |
| `apps/api/src/yupay/core/config.py`                               | five `nova_*` settings                                        |
| `apps/api/src/yupay/modules/fulfillment/suppliers/nova_client.py` | transport: wire format, errors, no interpretation             |
| `apps/api/src/yupay/modules/fulfillment/suppliers/nova.py`        | `Fulfiller`: mapping → order, status → outcome, money grading |
| `apps/api/src/yupay/modules/fulfillment/suppliers/__init__.py`    | registry entry                                                |
| `apps/api/src/yupay/modules/integrations/models.py`               | `MAPPING_REQUIRED_SUPPLIERS`                                  |
| `apps/api/src/yupay/modules/integrations/routes.py`               | `_nova_fulfiller_or_none`                                     |
| `apps/api/src/yupay/modules/integrations/player_check_nova.py`    | the whole fallback: targets, breaker, cache, region guard     |
| `apps/api/src/yupay/modules/integrations/player_check.py`         | two dispatch hooks, nothing more                              |
| `apps/api/src/yupay/modules/sourcing/service.py`                  | deterministic mapping order                                   |
| `apps/scheduler/src/yupay_scheduler/jobs/nova_reconcile.py`       | poll in-flight nova tasks                                     |
| `apps/admin/src/features/integrations/types.ts`                   | `nova` in the supplier lists                                  |
| `scripts/seed/2026-09-17_nova_mappings.py`                        | match our SKUs to their offers, upsert mappings               |
| `docs/decisions/0081-nova-reserve-supplier.md`                    | the decision                                                  |
| `docs/runbooks/nova.md`                                           | funding, switching, first live order, kill switch             |

---

## Task 1: NOVA client and settings

**Files:**

- Create: `apps/api/src/yupay/modules/fulfillment/suppliers/nova_client.py`
- Modify: `apps/api/src/yupay/core/config.py` (after the `gengine_*` block, around line 770)
- Test: `apps/api/tests/contract/test_nova_client.py`

**Interfaces:**

- Consumes: nothing from other tasks.
- Produces: `NovaClient`, `NovaError(message, *, status, code, body)`, `NovaUnavailableError`, `NovaValidation(valid, player_name, region)`; methods `get_balance()`, `list_topups()`, `get_offers(category_id)`, `create_topup_order(*, category_id, offer_id, fields, idempotency_key)`, `get_order(order_id)`, `validate_id(*, category_id, fields, timeout=None)`, `check_steam_login(steam_login, *, timeout=None)`. Settings `nova_api_key`, `nova_base_url`, `nova_request_timeout_seconds`, `nova_check_timeout_seconds`, `nova_player_check_enabled`.

- [ ] **Step 1: Write the failing contract tests**

`apps/api/tests/contract/test_nova_client.py`:

```python
"""Wire-format contract for the NOVA client.

Every fixture below is the shape the live API returned when this integration
was written (nova-gifts.com, key held out of the repo). Two things are easy to
get wrong here and impossible to notice until an order is lost:

* every response carries ``ok``, so a refusal can arrive as an HTTP 200 with
  ``ok: false`` — the status code alone never says whether a call worked;
* the validate namespace is not the top-up namespace (``mobile_legends``
  validates, ``mobile_legends_ru`` sells), so the two never share an id.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from yupay.modules.fulfillment.suppliers.nova_client import (
    NovaClient,
    NovaError,
    NovaUnavailableError,
)

pytestmark = pytest.mark.asyncio

BASE = "https://nova-gifts.com"


def _client(timeout: float = 5) -> NovaClient:
    return NovaClient(api_key="test-key", base_url=BASE, timeout_seconds=timeout)


@respx.mock
async def test_balance_carries_the_key_in_a_header() -> None:
    route = respx.get(f"{BASE}/api/v2/balance").mock(
        return_value=httpx.Response(200, json={"ok": True, "balance": "0.0000", "currency": "USD"})
    )
    assert (await _client().get_balance())["balance"] == "0.0000"
    # A key in a header stays out of proxy logs and browser history.
    assert route.calls.last.request.headers["X-API-Key"] == "test-key"


@respx.mock
async def test_ok_false_on_a_200_is_a_refusal() -> None:
    respx.get(f"{BASE}/api/v2/balance").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "nope", "code": "bad_thing"})
    )
    with pytest.raises(NovaError) as excinfo:
        await _client().get_balance()
    assert excinfo.value.code == "bad_thing"
    assert excinfo.value.status == 200


@respx.mock
async def test_blocked_account_keeps_its_code() -> None:
    respx.get(f"{BASE}/api/v2/balance").mock(
        return_value=httpx.Response(
            403,
            json={
                "ok": False,
                "error": "subscription inactive",
                "blockReason": None,
                "code": "subscription_inactive",
            },
        )
    )
    with pytest.raises(NovaError) as excinfo:
        await _client().get_balance()
    assert excinfo.value.status == 403
    assert excinfo.value.code == "subscription_inactive"


@respx.mock
async def test_topups_are_walked_by_cursor() -> None:
    # The cursor route is registered FIRST on purpose: respx matches params as
    # a subset, so a route keyed on `limit` alone would also swallow the
    # second request and the walk would never terminate.
    respx.get(f"{BASE}/api/v2/topups", params={"limit": "100", "cursor": "c2"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "kind": "topup",
                "items": [{"category_id": "pubg_mobile_auto", "name": "PUBG Mobile (Auto)"}],
                "meta": {"total": 2, "limit": 100, "next_cursor": None, "has_more": False},
            },
        )
    )
    respx.get(f"{BASE}/api/v2/topups", params={"limit": "100"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "kind": "topup",
                "items": [{"category_id": "mobile_legends_ru", "name": "Mobile Legends (RU)"}],
                "meta": {"total": 2, "limit": 100, "next_cursor": "c2", "has_more": True},
            },
        )
    )
    items = await _client().list_topups()
    assert [i["category_id"] for i in items] == ["mobile_legends_ru", "pubg_mobile_auto"]


@respx.mock
async def test_order_create_sends_the_idempotency_key_and_unwraps_the_order() -> None:
    route = respx.post(f"{BASE}/api/v2/topups/order").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "order": {"id": "ord_1", "status": "processing"}}
        )
    )
    order = await _client().create_topup_order(
        category_id="mobile_legends_ru",
        offer_id="275_diamonds",
        fields={"player_id": "1313232551", "server_id": "6618"},
        idempotency_key="task-42",
    )
    assert order == {"id": "ord_1", "status": "processing"}
    assert route.calls.last.request.headers["Idempotency-Key"] == "task-42"


@respx.mock
async def test_validate_id_maps_a_positive_verdict() -> None:
    respx.post(f"{BASE}/api/v2/topups/validate-id").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "category_id": "mobile_legends",
                "valid": True,
                "player_name": "blood moon",
                "player_id": "1313232551",
                "region": "Russia",
            },
        )
    )
    out = await _client().validate_id(
        category_id="mobile_legends", fields={"player_id": "1313232551", "zone_id": "6618"}
    )
    assert (out.valid, out.player_name, out.region) == (True, "blood moon", "Russia")


@respx.mock
async def test_validate_id_maps_a_negative_verdict() -> None:
    respx.post(f"{BASE}/api/v2/topups/validate-id").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "category_id": "pubg_mobile", "valid": False, "player_name": None},
        )
    )
    out = await _client().validate_id(category_id="pubg_mobile", fields={"player_id": "1"})
    assert out.valid is False
    assert out.player_name is None


@respx.mock
async def test_validate_id_422_is_an_error_not_a_verdict() -> None:
    respx.post(f"{BASE}/api/v2/topups/validate-id").mock(
        return_value=httpx.Response(422, json={"ok": False, "error": "could not confirm"})
    )
    with pytest.raises(NovaError):
        await _client().validate_id(category_id="pubg_mobile", fields={"player_id": "1"})


@respx.mock
async def test_steam_login_check_returns_the_boolean() -> None:
    respx.post(f"{BASE}/api/v2/steam-topup/check-login").mock(
        return_value=httpx.Response(200, json={"ok": True, "can_refill": True})
    )
    assert await _client().check_steam_login("someone") is True


@respx.mock
async def test_a_network_error_is_unavailable_not_a_refusal() -> None:
    respx.get(f"{BASE}/api/v2/balance").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(NovaUnavailableError):
        await _client().get_balance()


@respx.mock
async def test_non_json_is_a_refusal_with_the_body_kept() -> None:
    respx.get(f"{BASE}/api/v2/balance").mock(return_value=httpx.Response(502, text="<html>nginx"))
    with pytest.raises(NovaError) as excinfo:
        await _client().get_balance()
    assert "nginx" in excinfo.value.body
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd apps/api && uv run pytest tests/contract/test_nova_client.py -q`
Expected: collection error — `nova_client` does not exist.

- [ ] **Step 3: Add the settings**

In `apps/api/src/yupay/core/config.py`, directly after the `gengine_request_timeout_seconds` line:

```python
    # NOVA (nova-gifts.com) — reserve source for game top-ups, and the fallback
    # for the player check when G2B errors or rate-limits us. Same
    # empty-key-disables rule as the three above. Two timeouts, not one: the
    # advisory check runs with a customer watching a spinner and must not
    # double the wait a healthy G2B check already costs (830ms-4.9s measured),
    # while an order may take as long as the others do.
    nova_api_key: str = Field(default="")
    nova_base_url: str = Field(default="https://nova-gifts.com")
    nova_request_timeout_seconds: float = Field(default=20.0)
    nova_check_timeout_seconds: float = Field(default=4.0)
    # Kill switch for the fallback check alone: clearing the key disables
    # everything, this leaves top-ups working while the check is off.
    nova_player_check_enabled: bool = Field(default=True)
```

- [ ] **Step 4: Write the client**

`apps/api/src/yupay/modules/fulfillment/suppliers/nova_client.py`:

```python
"""HTTP client for NOVA's public API v2 (nova-gifts.com).

Transport only: it speaks the wire format and raises on refusals. Order state
interpretation lives in the fulfiller that wraps this client.

Three things about this API drive the shape below, all verified against the
live service on 2026-09-17:

* Auth is an ``X-API-Key`` header (``ng_…``).
* **Every response carries ``ok``.** A refusal can arrive as an HTTP 200 with
  ``ok: false``, so the status code alone never decides whether a call worked.
* **Validate ids and top-up ids are different namespaces.** ``mobile_legends``
  validates a player; ``mobile_legends_global`` and ``mobile_legends_ru`` sell
  to one. Nothing in the API links them, and passing one where the other
  belongs is a 404 at best.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from yupay.core.logging import get_logger

log = get_logger("yupay.fulfillment.nova")

#: Their own ceiling on ``limit``.
MAX_PAGE = 100


class NovaError(Exception):
    """NOVA refused the call (transport fine, business failure).

    Args:
        message: Their ``error`` string, or a synthesised one.
        status: HTTP status. ``200`` when the refusal came as ``ok: false``.
        code: Their machine-readable ``code``, when they sent one. It is
            optional in their schema, so no caller may require it.
        body: The raw response text, truncated. Kept for the same reason the
            G2B and G-Engine clients keep it: a caller sometimes has to re-read
            the payload to tell a real fault from a legitimate verdict.
    """

    def __init__(
        self, message: str, *, status: int = 200, code: str = "", body: str = ""
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body


class NovaUnavailableError(Exception):
    """NOVA could not be reached at all (network error, timeout, DNS)."""


@dataclass(frozen=True)
class NovaValidation:
    """One ``POST /topups/validate-id`` answer.

    Attributes:
        valid: Whether the id exists for that game.
        player_name: The nickname, when they report one.
        region: Their region word (observed: ``"Russia"``). Its meaning across
            our region-split brands is unproven — see the design doc's open
            questions — so only the fallback's region guard reads it.
    """

    valid: bool
    player_name: str | None
    region: str | None


class NovaClient:
    """Thin async client over the endpoints this integration uses."""

    def __init__(self, *, api_key: str, base_url: str, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    @contextlib.asynccontextmanager
    async def _session(self, *, timeout: float | None = None) -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout or self._timeout,
            headers={"X-API-Key": self._api_key, "Accept": "application/json"},
        ) as client:
            yield client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """One call. Raises :class:`NovaUnavailableError` when nothing was
        decided upstream, :class:`NovaError` when they answered a refusal."""
        try:
            async with self._session(timeout=timeout) as client:
                resp = await client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            # Network-level: nothing was decided upstream, which is a different
            # fact from a refusal and is graded differently by the caller.
            raise NovaUnavailableError(str(exc)) from exc

        text = resp.text[:500]
        log.info("nova.request", method=method, path=path, status=resp.status_code)
        try:
            body = resp.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise NovaError("nova returned non-JSON", status=resp.status_code, body=text)
        if resp.status_code >= 400 or body.get("ok") is not True:
            raise NovaError(
                str(body.get("error") or f"nova HTTP {resp.status_code}"),
                status=resp.status_code,
                code=str(body.get("code") or ""),
                body=text,
            )
        return body

    # ---------- probes ----------

    async def get_balance(self) -> dict[str, Any]:
        """``GET /balance`` — reachability, key validity and funds in one call."""
        return await self._request("GET", "/api/v2/balance")

    # ---------- catalogue ----------

    async def list_topups(self) -> list[dict[str, Any]]:
        """Every top-up category, walking their cursor to the end."""
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _page in range(50):
            params: dict[str, Any] = {"limit": MAX_PAGE}
            if cursor:
                params["cursor"] = cursor
            body = await self._request("GET", "/api/v2/topups", params=params)
            items += [i for i in (body.get("items") or []) if isinstance(i, dict)]
            cursor = ((body.get("meta") or {}).get("next_cursor")) or None
            if not cursor:
                break
        return items

    async def get_offers(self, category_id: str) -> dict[str, Any]:
        """Offers and input fields for one category."""
        return await self._request(
            "GET", "/api/v2/topups/offers", params={"category_id": category_id}
        )

    # ---------- ordering ----------

    async def create_topup_order(
        self,
        *,
        category_id: str,
        offer_id: str,
        fields: dict[str, str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Place one top-up order and return their order object.

        The key always travels: their parameter documentation calls it required
        even though the schema marks it optional, and a retry without one would
        be a second purchase. Their two descriptions disagree on what a *reused*
        key does (returns the original, or is rejected), which is why the
        fulfiller grades a 409 as undecided rather than as a free retry.
        """
        body = await self._request(
            "POST",
            "/api/v2/topups/order",
            json={"category_id": category_id, "offer_id": offer_id, "fields": fields},
            headers={"Idempotency-Key": idempotency_key[:255]},
        )
        order = body.get("order")
        return order if isinstance(order, dict) else {}

    async def get_order(self, order_id: str) -> dict[str, Any]:
        """One order by their public id."""
        body = await self._request("GET", f"/api/v2/orders/{order_id}")
        order = body.get("order")
        return order if isinstance(order, dict) else {}

    # ---------- advisory checks ----------

    async def validate_id(
        self, *, category_id: str, fields: dict[str, str], timeout: float | None = None
    ) -> NovaValidation:
        """Check a player id. A ``422`` ("could not be confirmed") raises."""
        body = await self._request(
            "POST",
            "/api/v2/topups/validate-id",
            json={"category_id": category_id, "fields": fields},
            timeout=timeout,
        )
        name = body.get("player_name")
        region = body.get("region")
        return NovaValidation(
            valid=bool(body.get("valid")),
            player_name=str(name) if name else None,
            region=str(region) if region else None,
        )

    async def check_steam_login(self, steam_login: str, *, timeout: float | None = None) -> bool:
        """Whether NOVA can top up that Steam account.

        Note what this is not: ``False`` says *they* cannot refill it, which is
        a weaker statement than "no such account" and must never be reported to
        a customer as an invalid login.
        """
        body = await self._request(
            "POST",
            "/api/v2/steam-topup/check-login",
            json={"steamLogin": steam_login},
            timeout=timeout,
        )
        return bool(body.get("can_refill"))


__all__ = [
    "MAX_PAGE",
    "NovaClient",
    "NovaError",
    "NovaUnavailableError",
    "NovaValidation",
]
```

- [ ] **Step 5: Run the tests to green**

Run: `cd apps/api && uv run pytest tests/contract/test_nova_client.py -q`
Expected: 11 passed.

- [ ] **Step 6: Lint and typecheck**

Run: `cd apps/api && uv run ruff format src/yupay/modules/fulfillment/suppliers/nova_client.py src/yupay/core/config.py tests/contract/test_nova_client.py && uv run ruff check src/yupay/modules/fulfillment/suppliers/nova_client.py tests/contract/test_nova_client.py && uv run mypy src/yupay/modules/fulfillment/suppliers/nova_client.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/yupay/modules/fulfillment/suppliers/nova_client.py apps/api/src/yupay/core/config.py apps/api/tests/contract/test_nova_client.py
git commit -m "feat(api/integrations): add the NOVA API client and settings"
```

---

## Task 2: NOVA fulfiller

**Files:**

- Create: `apps/api/src/yupay/modules/fulfillment/suppliers/nova.py`
- Modify: `apps/api/src/yupay/modules/fulfillment/suppliers/__init__.py`, `apps/api/src/yupay/modules/integrations/models.py:45`, `apps/api/src/yupay/modules/integrations/routes.py` (after `_waxpeer_fulfiller_or_none`, ~line 344)
- Test: `apps/api/tests/unit/test_nova_fulfiller.py`, `apps/api/tests/unit/test_supplier_money_outcome.py`

**Interfaces:**

- Consumes: `NovaClient`, `NovaError`, `NovaUnavailableError` from Task 1.
- Produces: `NovaFulfiller` (slug `nova`, `available`, `_client()`), `LOW_BALANCE_ERROR` re-used from `fulfillment.service`, and `_nova_fulfiller_or_none()` in `integrations.routes` for Task 5.

- [ ] **Step 1: Write the failing unit tests**

`apps/api/tests/unit/test_nova_fulfiller.py` — a fake client, no network:

```python
"""Unit tests for the NOVA fulfiller.

The money grading is the point of this file. NOVA charges on create ("Balance
is charged immediately"), so the difference between "they refused the request"
and "the call broke" is the difference between our money being here and our
money being unaccounted for.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from yupay.modules.fulfillment.suppliers.base import FulfillerError, MoneyOutcome
from yupay.modules.fulfillment.suppliers.nova import LOW_BALANCE_ERROR, NovaFulfiller
from yupay.modules.fulfillment.suppliers.nova_client import NovaError, NovaUnavailableError

pytestmark = pytest.mark.asyncio


class _FakeClient:
    """Records what was called, so "did it order at all" is answerable."""

    def __init__(self, *, order: dict[str, Any] | None = None, raises: Exception | None = None):
        self._order = order or {}
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def create_topup_order(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._order

    async def get_order(self, order_id: str) -> dict[str, Any]:  # noqa: ARG002
        if self._raises is not None:
            raise self._raises
        return self._order


def _mapping(**over: Any) -> Any:
    base = {
        "kind": "game",
        "external_product_id": "mobile_legends_ru",
        "external_variant_id": "275_diamonds",
    }
    base.update(over)
    return SimpleNamespace(**base)


def _item(**over: Any) -> Any:
    base = {
        "sku_id": "sku-1",
        "qty": 1,
        "fulfillment_data": {"player_id": "1313232551", "server": "6618"},
    }
    base.update(over)
    return SimpleNamespace(**base)


def _fulfiller(
    client: _FakeClient, monkeypatch: pytest.MonkeyPatch, *, available: bool = True
) -> NovaFulfiller:
    """The adapter with its key faked in.

    ``available`` reads settings, and settings are cached for the process, so
    the house pattern (see ``test_gengine_fulfiller.py``) patches the property
    rather than the environment.
    """
    monkeypatch.setattr(NovaFulfiller, "available", property(lambda _self: available))
    return NovaFulfiller(client=client)  # type: ignore[arg-type]


async def _fulfill(
    client: _FakeClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    item: Any = None,
    mapping: Any = None,
    available: bool = True,
) -> Any:
    """Run ``fulfill`` with the mapping lookup stubbed, so ``db`` is never touched."""
    import yupay.modules.fulfillment.suppliers.nova as mod

    row = mapping if mapping is not None else _mapping()

    async def _mapping_for(_db: Any, *, sku_id: str) -> Any:  # noqa: ARG001
        return row

    monkeypatch.setattr(mod, "_mapping_for", _mapping_for)
    return await _fulfiller(client, monkeypatch, available=available).fulfill(
        db=None,  # type: ignore[arg-type]
        order=SimpleNamespace(),  # type: ignore[arg-type]
        item=item if item is not None else _item(),
        idempotency_key="task-42",
    )


async def test_a_created_order_is_in_progress_and_keeps_its_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(order={"id": "ord_1", "status": "processing"})
    result = await _fulfill(client, monkeypatch)
    assert result.outcome == "in_progress"
    assert result.external_order_id == "ord_1"
    assert result.money_outcome is None
    # Our own field names are renamed to theirs: `server` -> `server_id`.
    assert client.calls[0]["fields"] == {"player_id": "1313232551", "server_id": "6618"}
    assert client.calls[0]["idempotency_key"] == "task-42"
    assert client.calls[0]["category_id"] == "mobile_legends_ru"
    assert client.calls[0]["offer_id"] == "275_diamonds"


async def test_a_completed_order_delivers_a_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await _fulfill(_FakeClient(order={"id": "ord_1", "status": "completed"}), monkeypatch)
    assert result.outcome == "succeeded"
    assert result.artifact_kind == "topup_receipt"
    assert result.money_outcome is None


async def test_an_unknown_status_stays_in_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """Their order object is untyped; a word we have never seen must not end
    the task in either direction."""
    result = await _fulfill(_FakeClient(order={"id": "ord_1", "status": "half_done"}), monkeypatch)
    assert result.outcome == "in_progress"


async def test_a_refunded_order_says_the_money_came_back(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await _fulfill(_FakeClient(order={"id": "ord_1", "status": "refunded"}), monkeypatch)
    assert result.outcome == "failed"
    assert result.money_outcome is MoneyOutcome.RETURNED


async def test_a_failed_order_without_a_refund_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await _fulfill(_FakeClient(order={"id": "ord_1", "status": "failed"}), monkeypatch)
    assert result.outcome == "failed"
    assert result.money_outcome is MoneyOutcome.UNKNOWN


@pytest.mark.parametrize(
    ("status", "money"),
    [
        (400, MoneyOutcome.RETURNED),
        (403, MoneyOutcome.RETURNED),
        (404, MoneyOutcome.RETURNED),
        (409, MoneyOutcome.UNKNOWN),
        (500, MoneyOutcome.UNKNOWN),
    ],
)
async def test_refusals_are_graded_by_status(
    monkeypatch: pytest.MonkeyPatch, status: int, money: MoneyOutcome
) -> None:
    client = _FakeClient(raises=NovaError("no", status=status))
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch)
    assert excinfo.value.money_outcome is money


async def test_unreachable_on_the_create_may_have_spent(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(raises=NovaUnavailableError("boom"))
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch)
    assert excinfo.value.money_outcome is MoneyOutcome.UNKNOWN


async def test_low_balance_is_a_stall_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The saga keys on this exact string to park the task and alert ops."""
    client = _FakeClient(raises=NovaError("insufficient balance", status=400))
    result = await _fulfill(client, monkeypatch)
    assert result.outcome == "failed"
    assert result.error == LOW_BALANCE_ERROR
    assert result.money_outcome is None


async def test_a_multi_quantity_item_is_refused_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One call buys one offer: their order endpoint has no quantity."""
    client = _FakeClient(order={"id": "ord_1", "status": "processing"})
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch, item=_item(qty=2))
    assert excinfo.value.money_outcome is MoneyOutcome.RETURNED
    assert client.calls == []


async def test_a_mapping_without_an_offer_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch, mapping=_mapping(external_variant_id=None))
    assert excinfo.value.money_outcome is MoneyOutcome.RETURNED
    assert client.calls == []


async def test_no_usable_fields_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch, item=_item(fulfillment_data={"email": "a@b.c"}))
    assert excinfo.value.money_outcome is MoneyOutcome.RETURNED
    assert client.calls == []


async def test_an_unconfigured_key_never_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfill(client, monkeypatch, available=False)
    assert excinfo.value.money_outcome is MoneyOutcome.RETURNED
    assert client.calls == []


async def test_check_status_without_an_id_stays_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(external_order_id=None, extra_metadata={})
    status = await _fulfiller(_FakeClient(), monkeypatch).check_status(
        db=None,  # type: ignore[arg-type]
        task=task,  # type: ignore[arg-type]
    )
    assert status.outcome == "in_progress"


async def test_check_status_that_cannot_read_says_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(external_order_id="ord_1", extra_metadata={})
    client = _FakeClient(raises=NovaUnavailableError("boom"))
    with pytest.raises(FulfillerError) as excinfo:
        await _fulfiller(client, monkeypatch).check_status(db=None, task=task)  # type: ignore[arg-type]
    assert excinfo.value.money_outcome is MoneyOutcome.UNKNOWN


async def test_the_same_task_always_sends_the_same_key_and_never_retries_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The idempotent re-call leg AGENTS.md §8 requires of a supplier adapter.

    Their two descriptions of a reused `Idempotency-Key` disagree — one says it
    returns the original order, the other says it is rejected — so the only
    behaviour we can assert, and the only one that is safe under either, is
    this: one `fulfill` call makes exactly one create, and a second `fulfill`
    for the same task sends the same key rather than a fresh one. A retry that
    minted a new key would be a second purchase whichever way their server
    behaves.
    """
    client = _FakeClient(order={"id": "ord_1", "status": "processing"})
    await _fulfill(client, monkeypatch)
    await _fulfill(client, monkeypatch)
    assert len(client.calls) == 2
    assert {c["idempotency_key"] for c in client.calls} == {"task-42"}


async def test_check_status_reads_a_finished_order(monkeypatch: pytest.MonkeyPatch) -> None:
    task = SimpleNamespace(external_order_id="ord_1", extra_metadata={})
    client = _FakeClient(order={"id": "ord_1", "status": "completed"})
    status = await _fulfiller(client, monkeypatch).check_status(
        db=None,  # type: ignore[arg-type]
        task=task,  # type: ignore[arg-type]
    )
    assert status.outcome == "succeeded"
    assert status.artifact_kind == "topup_receipt"
```

The fixture pattern above is the one `tests/unit/test_gengine_fulfiller.py` already uses
(`monkeypatch.setattr(GEngineFulfiller, "available", property(...))` plus a patched
`_mapping_for`). Do not invent a second one, and do not reach for `monkeypatch.setenv`:
settings are cached for the whole process, so an env var set inside a test never reaches `available`.

- [ ] **Step 2: Run them and watch them fail**

Run: `cd apps/api && uv run pytest tests/unit/test_nova_fulfiller.py -q`
Expected: collection error — `nova` does not exist.

- [ ] **Step 3: Write the fulfiller**

`apps/api/src/yupay/modules/fulfillment/suppliers/nova.py`. Docstring first — it carries the two facts that decide everything else:

```python
"""``Fulfiller`` for NOVA (nova-gifts.com) game top-ups.

NOVA is a **reserve**: its catalogue covers essentially every game brand we
sell, and it earns its place as somewhere to send an order when G2B is out of
stock, short on balance, or down. Nothing routes there on its own — sourcing
keeps the incumbent mapping and an operator switches a SKU with
``force_supplier`` (see ``docs/runbooks/nova.md``).

Two facts from their API shape this adapter:

* **The create spends.** "Balance is charged immediately; then ``processing``
  until completed/refund." So this grades money like Waxpeer, not like
  G-Engine: a create that failed on or after the call leaves both answers open
  and is :attr:`MoneyOutcome.UNKNOWN`, never "returned".
* **Their order object is untyped** in their own OpenAPI (``order: {}``). The
  status table below is therefore an allow-list, and anything outside it is
  ``in_progress`` — reading an unknown word as success would mark undelivered
  goods delivered, and reading it as failure would start reconciliation on
  money that may still complete normally. The first live order is a documented
  runbook step precisely because it is what turns this guess into a fact.
"""
```

Then:

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.base import (
    Fulfiller,
    FulfillerError,
    FulfillerNotIntegratedError,
    FulfillResult,
    FulfillStatus,
    MoneyOutcome,
)
from yupay.modules.fulfillment.suppliers.nova_client import (
    NovaClient,
    NovaError,
    NovaUnavailableError,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yupay.modules.fulfillment.models import FulfillmentTask
    from yupay.modules.orders.models import Order, OrderItem

log = get_logger("yupay.fulfillment.nova")

#: Our form-field keys -> their `fields` keys. Our checkout already collects
#: these; this is only the rename. Unrecognised keys are dropped, as in the
#: G-Engine adapter: an unmapped field is more likely a form we have not taught
#: this adapter about than something NOVA wants.
_FIELD_MAP: dict[str, str] = {
    "player_id": "player_id",
    "account": "player_id",
    "server": "server_id",
    "server_id": "server_id",
    "zone": "server_id",
    "zone_id": "server_id",
}

#: Must equal ``fulfillment.service._LOW_BALANCE_ERROR`` — the saga keys on
#: this exact string to keep the customer on "processing", park the task in the
#: admin inbox and alert ops instead of failing the order. A guard test locks
#: the match (see ``test_supplier_money_outcome.py``).
LOW_BALANCE_ERROR = "supplier_low_balance"

#: They document no code for it, so we sniff the message. A false positive only
#: demotes a hard failure to a retryable one, which is the safer mistake.
_LOW_BALANCE_HINTS = ("not enough balance", "insufficient balance", "insufficient funds")

_IN_FLIGHT = frozenset(
    {"pending", "preparing", "prepared", "debited", "processing", "in_progress", "created",
     "queued", "new"}
)
_SUCCESS = frozenset({"completed", "success", "delivered", "done"})
_REFUNDED = frozenset({"refunded", "refund"})
_FAILED = frozenset({"failed", "error", "cancelled", "canceled"})

#: A refusal raised before any call, or one their API answered with — nothing
#: was charged.
_NOTHING_SPENT = MoneyOutcome.RETURNED
#: A failure on or after the call that spends.
_MAY_HAVE_SPENT = MoneyOutcome.UNKNOWN
```

Helpers, each with a docstring:

```python
def _status_of(obj: dict[str, Any]) -> str:
    """Their order status, lowercased. ``""`` when the object carries none.

    Reads ``status`` then ``state``. The warning is how we learn their real
    shape from the first live order — their spec types this object as ``{}``.
    """
    raw = obj.get("status") or obj.get("state") or ""
    text = str(raw).strip().lower()
    if not text:
        log.warning("nova.order_without_status", keys=sorted(str(k) for k in obj)[:10])
    return text


def _order_id_of(obj: dict[str, Any]) -> str | None:
    """Their order id, as a string. ``None`` when we cannot find one."""
    for key in ("id", "order_id", "public_id", "uuid"):
        value = obj.get(key)
        if value not in (None, ""):
            return str(value)
    log.warning("nova.order_without_id", keys=sorted(str(k) for k in obj)[:10])
    return None


def _fields_from(item: OrderItem) -> dict[str, str]:
    """Their ``fields`` payload, built from our form data."""
    data = item.fulfillment_data or {}
    out: dict[str, str] = {}
    for key, value in data.items():
        target = _FIELD_MAP.get(str(key).lower())
        if target and str(value).strip():
            out.setdefault(target, str(value).strip())
    return out


def _looks_like_low_balance(exc: NovaError) -> bool:
    """Whether a refusal is a "top up your balance" one."""
    text = f"{exc} {exc.body} {exc.code}".lower()
    return any(hint in text for hint in _LOW_BALANCE_HINTS)


def _refusal_money(exc: NovaError) -> MoneyOutcome:
    """What a refusal says about our money.

    400/403/404 are refusals of the request itself — an unknown category or
    offer, a malformed field, an inactive subscription — and they happen before
    anything is charged. A 409 is their idempotency refusal, and their two
    descriptions of it disagree (the endpoint says a reused key returns the
    original order, the parameter says it is rejected), so it cannot tell us
    whether the first attempt charged us. 5xx is the same kind of open
    question with a different cause.
    """
    return _NOTHING_SPENT if exc.status in (400, 403, 404) else _MAY_HAVE_SPENT


def _receipt(order_id: str | None, status: str) -> dict[str, Any]:
    """What the customer sees. Deliberately thin: a top-up has no code to hand
    over, only proof that it happened."""
    return {"supplier": "nova", "external_order_id": order_id, "status": status}


def _meta(status: str) -> dict[str, Any]:
    return {"supplier": "nova", "nova_status": status}


def _low_balance_result() -> FulfillResult:
    """A soft low-balance failure the saga parks in the inbox and alerts on."""
    return FulfillResult(
        outcome="failed",
        external_order_id=None,
        artifact_kind=None,
        artifact=None,
        error=LOW_BALANCE_ERROR,
        extra_metadata={"supplier": "nova"},
        # Deliberately unclassified: the order is not finished failing.
        money_outcome=None,
    )


def _result(obj: dict[str, Any]) -> FulfillResult:
    """Interpret one order object into a fulfilment result."""
    status = _status_of(obj)
    order_id = _order_id_of(obj)
    if status in _SUCCESS:
        return FulfillResult(
            outcome="succeeded",
            external_order_id=order_id,
            artifact_kind="topup_receipt",
            artifact=_receipt(order_id, status),
            error=None,
            extra_metadata=_meta(status),
            money_outcome=None,
        )
    if status in _REFUNDED:
        return FulfillResult(
            outcome="failed",
            external_order_id=order_id,
            artifact_kind=None,
            artifact=None,
            error=f"nova refunded the order ({status})",
            extra_metadata={**_meta(status), "supplier_refunded": True},
            money_outcome=MoneyOutcome.RETURNED,
        )
    if status in _FAILED:
        return FulfillResult(
            outcome="failed",
            external_order_id=order_id,
            artifact_kind=None,
            artifact=None,
            error=f"nova order {status}",
            extra_metadata={**_meta(status), "needs_reconciliation": True},
            money_outcome=_MAY_HAVE_SPENT,
        )
    # Everything else, including a status we have never seen: still moving.
    return FulfillResult(
        outcome="in_progress",
        external_order_id=order_id,
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata=_meta(status),
        money_outcome=None,
    )
```

The class:

```python
class NovaFulfiller(Fulfiller):
    """``Fulfiller`` Protocol implementation for NOVA."""

    supplier = "nova"

    def __init__(self, client: NovaClient | None = None) -> None:
        # Injectable for tests; in prod a transient client is built per call so
        # a hot-reloaded key takes effect without a restart (same as g2b).
        self._client_override = client

    def _client(self) -> NovaClient:
        if self._client_override is not None:
            return self._client_override
        s = get_settings()
        return NovaClient(
            api_key=s.nova_api_key,
            base_url=s.nova_base_url,
            timeout_seconds=s.nova_request_timeout_seconds,
        )

    @property
    def available(self) -> bool:
        return bool(get_settings().nova_api_key)

    async def fulfill(self, *, db, order, item, idempotency_key) -> FulfillResult:
        ...
    async def check_status(self, *, db, task) -> FulfillStatus:
        ...
    async def cancel(self, *, db, task) -> None:
        raise FulfillerNotIntegratedError(
            "nova exposes no cancel endpoint", money_outcome=MoneyOutcome.UNKNOWN
        )
```

`fulfill`, in order: refuse when unavailable (`_NOTHING_SPENT`); refuse `item.qty > 1` with "nova has no quantity on a top-up order — one call buys one offer" (`_NOTHING_SPENT`); load the mapping through a `_mapping_for(db, sku_id=item.sku_id)` copied from `gengine.py:563` with `supplier_slug == "nova"`; refuse when `external_product_id` or `external_variant_id` is blank; build `fields` and refuse when empty; then call `create_topup_order`, catching `NovaError` (low-balance first, then `FulfillerError(_refusal_money(exc))`) and `NovaUnavailableError` (`_MAY_HAVE_SPENT`); return `_result(obj)`.

`check_status`: unavailable → `FulfillerError(_MAY_HAVE_SPENT)` ("by the time anything polls, the order has been placed"); no `external_order_id` → `in_progress` (the create never got far enough to give us one, and the reconciler will keep looking); otherwise `get_order`, mapping `NovaError`/`NovaUnavailableError` to `FulfillerError(_MAY_HAVE_SPENT)`, and re-wrap `_result` into a `FulfillStatus` passing `money_outcome` through rather than re-deriving it.

- [ ] **Step 4: Register it**

In `suppliers/__init__.py`: import `NovaFulfiller`, add to `REGISTRY` after `gengine` with a comment ("Reserve for game top-ups: covers nearly the whole catalogue, routed to only by an explicit `force_supplier` rule. Same hot-reload rule — `available` reads the key per call."), and add to `__all__`.

In `integrations/models.py:45`:

```python
MAPPING_REQUIRED_SUPPLIERS: frozenset[str] = frozenset({"g2b", "gengine", "nova"})
```

In `integrations/routes.py`, after `_waxpeer_fulfiller_or_none`:

```python
def _nova_fulfiller_or_none() -> NovaFulfiller | None:
    """Return the registered NOVA adapter iff ``NOVA_API_KEY`` is set.

    Mirrors the two above — used by the player-check fallback in
    ``integrations.player_check_nova``.
    """
    from yupay.modules.fulfillment.suppliers import REGISTRY
    from yupay.modules.fulfillment.suppliers.nova import NovaFulfiller

    fulfiller = REGISTRY.get("nova")
    if isinstance(fulfiller, NovaFulfiller) and fulfiller.available:
        return fulfiller
    return None
```

- [ ] **Step 5: Add NOVA to the money-outcome matrix**

`apps/api/tests/unit/test_supplier_money_outcome.py` already enumerates every adapter's failure exits. Add NOVA's rows following the file's existing shape, including the guard that `nova.LOW_BALANCE_ERROR == service._LOW_BALANCE_ERROR`.

- [ ] **Step 6: Run the tests**

Run: `cd apps/api && uv run pytest tests/unit/test_nova_fulfiller.py tests/unit/test_supplier_money_outcome.py -q`
Expected: all pass.

Then the coverage gate for the adapter:
Run: `cd apps/api && uv run pytest tests/unit/test_nova_fulfiller.py --cov=yupay.modules.fulfillment.suppliers.nova --cov-report=term-missing -q`
Expected: ≥95 %. Add cases for whatever is missed — do not lower the gate.

- [ ] **Step 7: Lint, typecheck, commit**

```bash
cd apps/api && uv run ruff format src/yupay/modules/fulfillment/suppliers/nova.py && uv run ruff check src/yupay/modules/fulfillment/suppliers/nova.py
# mypy runs from the REPO ROOT — from apps/api it resolves `yupay.core.logging`
# as untyped and reports import errors on files that are already clean.
cd /Users/macbook_uz/Projects/yupay && uv run mypy apps/api/src/yupay/modules/fulfillment/suppliers/nova.py
git add apps/api/src/yupay/modules/fulfillment/suppliers apps/api/src/yupay/modules/integrations/models.py apps/api/src/yupay/modules/integrations/routes.py apps/api/tests/unit
git commit -m "feat(api/fulfillment): add the NOVA fulfiller for game top-ups"
```

---

## Task 3: Reconcile job

**Files:**

- Create: `apps/scheduler/src/yupay_scheduler/jobs/nova_reconcile.py`
- Modify: `apps/scheduler/src/yupay_scheduler/main.py` (import at ~line 48, register at ~line 84)
- Test: `apps/api/tests/integration/test_nova_reconcile.py`

**Interfaces:**

- Consumes: `NovaFulfiller.check_status` from Task 2.
- Produces: `register(scheduler)` and `run_nova_reconcile()`.

- [ ] **Step 1: Write the job**

Copy `apps/scheduler/src/yupay_scheduler/jobs/gengine_reconcile.py` verbatim and change: the module docstring, `log = get_logger("yupay.scheduler.nova_reconcile")`, `_JOB_ID = "fulfillment.nova_reconcile"`, `_SUPPLIER = "nova"`, the three log event names (`nova_reconcile.*`), and the function names (`run_nova_reconcile`, `_list_stuck_task_ids`, `_reconcile_one`). `_INTERVAL_SECONDS = 60`, `_PAGE_SIZE = 100`, `_MAX_PAGES = 50` stay.

The docstring says why this job exists, and it is a different why from G-Engine's:

```python
"""Reconcile in-flight NOVA top-ups.

NOVA has no webhook. An order is charged on create and then sits in
``processing`` until it completes or is refunded, so without a poll a finished
order is never noticed: the customer watches "в обработке" and the task never
leaves ``in_progress``. Unlike the G-Engine sweep, this one only *observes* —
nothing here spends money, because NOVA takes it at create time.

Runs every 60 seconds. Each stuck task is reconciled through
``fulfillment.process_webhook_update`` — the same supplier-generic reconciler a
real webhook route would call — in its own session and transaction, so one bad
task can never abort the batch.

Idempotent and safe to overlap: the sweep lists only tasks that are currently
``in_progress``, and ``process_webhook_update`` short-circuits one that already
reached a terminal state.
"""
```

- [ ] **Step 2: Register it**

`main.py`: add `nova_reconcile` to the jobs import block (alphabetical, after `merchant_feed`) and `nova_reconcile.register(scheduler)` beside the other reconcilers.

- [ ] **Step 3: Write the test**

`apps/api/tests/integration/test_nova_reconcile.py`, modelled on `test_gengine_reconcile.py`: an `in_progress` nova task whose order now reads `completed` is swept to `succeeded`; a task that raises does not stop the sweep of the next one. Import the job from `yupay_scheduler.jobs.nova_reconcile` exactly as the G-Engine test imports its own.

- [ ] **Step 4: Run it**

Run: `cd apps/api && uv run pytest tests/integration/test_nova_reconcile.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/scheduler apps/api/tests/integration/test_nova_reconcile.py
git commit -m "feat(scheduler): poll in-flight NOVA top-ups every 60s"
```

---

## Task 4: Deterministic supplier order in auto sourcing

**Files:**

- Modify: `apps/api/src/yupay/modules/sourcing/service.py` (the `mapping_slug` query in `_resolve_auto`, ~line 118)
- Test: `apps/api/tests/integration/test_inventory_sourcing_routes.py` — it already covers both `resolve_for_sku` and `set_rule`

**Interfaces:**

- Consumes: nothing. Produces: no new names; a behaviour guarantee later tasks rely on.

**Why this is in this branch:** a reserve mapping is the first time a top-up SKU will carry two active mappings, and the current query picks one with no `ORDER BY`. Today's single-mapping SKUs are stable by accident; add a second row and the primary route becomes whatever Postgres returns first, which can change after a `VACUUM` with nothing to announce it.

- [ ] **Step 1: Write the failing test**

```python
async def test_auto_keeps_the_older_mapping_when_a_reserve_is_added(db) -> None:
    """A reserve mapping must never take the route by being added.

    The older row is the incumbent: it is the one orders have been going to.
    Without an explicit order this test is a coin flip, which is exactly the
    bug — so it inserts the reserve first in *insert* order but older in
    ``created_at``, and asserts the created_at order wins.
    """
    # ... create a top_up SKU with a g2b mapping created_at 2026-01-01 and a
    # nova mapping created_at 2026-09-17, both active, no sourcing rule.
    decision = await resolve_for_sku(db, sku_id=sku.id)
    assert decision.primary == "supplier:g2b"
    assert decision.fallback == "supplier:manual"
```

- [ ] **Step 2: Run it**

Run: `cd apps/api && uv run pytest tests/integration/test_inventory_sourcing_routes.py -q -k reserve`
Expected: it may pass by luck. Run it twice; it proves nothing until the fix lands, which is the point of the comment above.

- [ ] **Step 3: Make it deterministic**

In `_resolve_auto`, replace the mapping query with:

```python
    # Order matters, and it did not used to. A top-up SKU with a reserve
    # supplier carries two active mappings, and `.limit(1)` with no ORDER BY
    # picks whichever row Postgres happens to return — which can change after a
    # VACUUM, silently moving somebody's orders to a different supplier. The
    # oldest active mapping is the incumbent: it is where orders have been
    # going, so it keeps the route, and a reserve added later can never take it
    # by being added. Switching suppliers stays an explicit `force_supplier`
    # decision. `supplier_slug` breaks a created_at tie so the answer is total.
    mapping_slug: str | None = (
        await db.execute(
            select(SkuSupplierMapping.supplier_slug)
            .where(
                SkuSupplierMapping.sku_id == sku_id,
                SkuSupplierMapping.is_active.is_(True),
            )
            .order_by(SkuSupplierMapping.created_at.asc(), SkuSupplierMapping.supplier_slug.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
```

Update the comment above it (currently "order doesn't matter") — it is now wrong.

- [ ] **Step 4: Cover the `force_supplier` guard for the new slug**

`nova` joined `MAPPING_REQUIRED_SUPPLIERS` in Task 2, so `sourcing.service.set_rule` must now
refuse `force_supplier = nova` on a SKU with no active nova mapping and accept it with one. Add
both cases beside the existing `g2b` / `gengine` ones in the same test module:

```python
async def test_force_supplier_nova_needs_an_active_mapping(db) -> None:
    with pytest.raises(ValidationError):
        await set_rule(db, sku_id=sku.id, mode="force_supplier",
                       supplier_slug="nova", admin_id="admin-1")
    # ... insert an active nova mapping ...
    rule = await set_rule(db, sku_id=sku.id, mode="force_supplier",
                          supplier_slug="nova", admin_id="admin-1")
    assert rule.supplier_slug == "nova"
```

- [ ] **Step 5: Run the whole sourcing suite**

Run: `cd apps/api && uv run pytest tests -q -k sourcing`
Expected: all pass, including the new one.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/yupay/modules/sourcing apps/api/tests
git commit -m "fix(api/sourcing): pick the oldest active mapping, not an arbitrary one"
```

---

## Task 5: Player-check fallback

**Files:**

- Create: `apps/api/src/yupay/modules/integrations/player_check_nova.py`
- Modify: `apps/api/src/yupay/modules/integrations/player_check.py` (only `check_player_for_brand_id` plus two small private hooks)
- Test: `apps/api/tests/unit/test_player_check_nova.py`

**Interfaces:**

- Consumes: `NovaClient.validate_id` / `check_steam_login` (Task 1), `_nova_fulfiller_or_none` (Task 2), and `player_check._cached`, `player_check._worth_caching`, `player_check._CACHE_TTL_SECONDS`.
- Produces: `NovaValidateTarget`, `NOVA_VALIDATE`, `fallback_for_brand(*, brand_slug, player_id, server_id)`, `fallback_for_steam(*, steam_login)` — both returning `PlayerCheckOut` and never raising.

**Non-negotiable:** the fallback returns `valid` or `error`. Never `invalid`. See Global Constraints.

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/unit/test_player_check_nova.py`, with a scripted fake client (no network, no DB):

```python
"""The NOVA fallback for the player check.

Two rules this file exists to lock:

* the fallback runs only when the primary answered ``error``;
* it can say ``valid`` or ``error``, never ``invalid`` — only ``invalid``
  blocks Pay (ADR-0031), and a supplier we consult precisely because we have no
  primary verdict may not be the sole basis for refusing a paying customer.
"""
```

Cases:

1. `fallback_for_brand` with a brand absent from `NOVA_VALIDATE` → `error`, and the client is never built.
2. `nova_player_check_enabled = False` → `error`, no call.
3. NOVA answers `valid: true, player_name: "blood moon", region: "Russia"` for `mobile-legends-ru` → `status="valid"`, `name="blood moon"`.
4. Same answer but the brand's `region_word` is not in `region` → `error`, and a `player_check_fallback_region_mismatch` warning was logged.
5. `region` missing entirely on a brand that expects one → `error` (the guard needs positive evidence, not the absence of contrary evidence).
6. NOVA answers `valid: false` → `error`, **not** `invalid`.
7. The client raises → `error`, and the breaker recorded a failure.
8. Breaker open → `error` with no call made.
9. A `valid` result is cached under `playercheck:nova:…` and a second call answers from the cache without a second request; an `error` result is not cached.
10. The zone value travels as `zone_id` (their validate field key), not `server_id` (their _order_ field key) — assert the request payload.
11. `fallback_for_steam`: `can_refill: true` → `valid`; `can_refill: false` → `error`; a raise → `error`.
12. No log line carries the raw `player_id` or `steam_login` — assert it with whatever capture helper the existing player-check tests already use (`rg -n "caplog|capture_logs" apps/api/tests/unit | head`), not a new one.

Then, in `apps/api/tests/unit/test_player_check_service.py` (the existing brand-check unit suite), three wiring cases:

13. Primary `valid` → NOVA never consulted.
14. Primary `invalid` → NOVA never consulted (the customer's mistake is already known).
15. Primary `error` → NOVA consulted once, and its `valid` is what the caller receives.

- [ ] **Step 2: Run them and watch them fail**

Run: `cd apps/api && uv run pytest tests/unit/test_player_check_nova.py -q`
Expected: collection error.

- [ ] **Step 3: Write the fallback module**

`apps/api/src/yupay/modules/integrations/player_check_nova.py`:

```python
"""NOVA as a second opinion for the player check.

The primary check (G2B for a game, Waxpeer for a Steam login) answers
``valid`` / ``invalid`` / ``error``. This module is consulted for exactly one
of those: **``error``**, which means we have no verdict at all — G2B rate-limited
us, refused, or could not be reached. ``valid`` and ``invalid`` are answers, and
an answer is never second-guessed.

**It can say ``valid`` or ``error``. It never says ``invalid``.** Three reasons,
in order of weight:

1. It only runs when there is no primary verdict, so its ``invalid`` would be
   the sole basis for blocking a paying customer (ADR-0031: ``invalid`` is the
   one verdict that blocks Pay).
2. Their MLBB validate category is one namespace for a catalogue we split into
   two brands, and the ``region`` word it returns is of unproven meaning.
3. It is how this codebase already treats an answer it cannot read:
   ``player_check._map_response`` returns ``error``, not ``invalid``, for a
   G2B verdict outside the two it recognises — precisely so the check never
   becomes a fake rejecter.

The cost is that a customer who mistypes during a G2B outage is told "could not
check" instead of "wrong id" — which is what they are told today. The gain, a
confirmed nickname while G2B is down, is kept in full.

**Their validate ids are not their top-up ids** (``mobile_legends`` validates,
``mobile_legends_ru`` sells) and their validate field key for a server is
``zone_id``, while the order endpoint wants ``server_id``. Both are easy to
cross and neither fails loudly.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from yupay.core.config import get_settings
from yupay.core.logging import get_logger, hash_short
from yupay.core.redis import get_redis
from yupay.modules.integrations.breaker import SupplierBreaker
from yupay.modules.integrations.schemas import PlayerCheckOut

if TYPE_CHECKING:
    from yupay.modules.fulfillment.suppliers.nova_client import NovaValidation

logger = get_logger("yupay.integrations.player_check_nova")

#: Same window and thresholds as the G2B breaker: three consecutive failures
#: catch a real outage within a few customers, and 30s is short enough that a
#: blip costs almost nobody a check.
_BREAKER_THRESHOLD = 3
_BREAKER_COOLDOWN_SECONDS = 30


@dataclass(frozen=True)
class NovaValidateTarget:
    """How one of our brands maps onto NOVA's validate namespace.

    Attributes:
        category_id: Their id in the **validate** namespace. Never a top-up
            ``category_id``; nothing in their API links the two.
        region_word: A lowercased substring their ``region`` must contain for
            this brand, or ``None`` when the game has one region worldwide. A
            brand that expects a word and gets nothing back fails the guard:
            the guard wants positive evidence, not the absence of contrary
            evidence.
    """

    category_id: str
    region_word: str | None


#: The brands NOVA may be asked about. A code table rather than a database
#: mapping on purpose: validation is brand-scoped where mappings are SKU-scoped,
#: NOVA validates five games in total, and adding a brand here should cost a
#: review of what its region word means rather than a row somebody can add in
#: the admin without thinking about it.
#:
#: ``mobile-legends`` (global) is deliberately absent. Their single
#: ``mobile_legends`` category has only ever been observed answering for a
#: Russian account, and a brand we cannot tell apart gets no fallback rather
#: than a guess. See the design doc's open questions for the one probe that
#: settles it.
NOVA_VALIDATE: dict[str, NovaValidateTarget] = {
    "mobile-legends-ru": NovaValidateTarget("mobile_legends", "russia"),
    "pubg-mobile": NovaValidateTarget("pubg_mobile", None),
    "free-fire": NovaValidateTarget("free_fire", None),
    "magic-chess-gogo": NovaValidateTarget("magic_chess_gogo_global", None),
    "magic-chess-gogo-ru": NovaValidateTarget("magic_chess_gogo_ru", None),
}


def _breaker() -> SupplierBreaker:
    """The circuit guarding NOVA's advisory calls.

    Separate from G2B's: this path is reached *because* G2B is unwell, so one
    supplier's outage must not open the other's circuit.
    """
    return SupplierBreaker(
        "nova:player_check",
        threshold=_BREAKER_THRESHOLD,
        cooldown_seconds=_BREAKER_COOLDOWN_SECONDS,
    )


def _cache_key(category_id: str, player_id: str, server_id: str | None) -> str:
    """Redis key for a cached NOVA verdict.

    Its own namespace, so a NOVA answer can never be served as a G2B one, and
    the id is hashed for the same PII reason (§9) as the primary's key.
    """
    return f"playercheck:nova:{category_id}:{server_id or '-'}:{hash_short(player_id)}"


def _steam_cache_key(steam_login: str) -> str:
    return f"playercheck:nova:steam:{hash_short(steam_login)}"
```

Then the two entry points. Both catch everything and degrade to `error`; neither raises.

```python
async def fallback_for_brand(
    *, brand_slug: str | None, player_id: str, server_id: str | None
) -> PlayerCheckOut:
    """Ask NOVA about a player id. Returns ``valid`` or ``error``, never ``invalid``.

    Args:
        brand_slug: Our brand. A slug absent from :data:`NOVA_VALIDATE` gets no
            call at all.
        player_id: Never logged, only hashed.
        server_id: The sibling server/zone value, sent as their ``zone_id``.
    """
    from yupay.modules.integrations.player_check import _CACHE_TTL_SECONDS, _cached, _worth_caching
    from yupay.modules.integrations.routes import _nova_fulfiller_or_none

    settings = get_settings()
    if not settings.nova_player_check_enabled:
        return PlayerCheckOut(status="error")
    target = NOVA_VALIDATE.get(brand_slug or "")
    if target is None:
        return PlayerCheckOut(status="error")

    key = _cache_key(target.category_id, player_id, server_id)
    cached = await _cached(key)
    if cached is not None:
        return cached

    fulfiller = _nova_fulfiller_or_none()
    if fulfiller is None:
        return PlayerCheckOut(status="error")

    breaker = _breaker()
    if await breaker.is_open():
        logger.info("player_check_fallback_short_circuited", provider="nova",
                    category_id=target.category_id)
        return PlayerCheckOut(status="error")

    # Their validate endpoint names the server `zone_id`; their order endpoint
    # names it `server_id`. Crossing the two is silent.
    fields = {"player_id": player_id}
    if server_id:
        fields["zone_id"] = server_id

    try:
        answer = await fulfiller._client().validate_id(
            category_id=target.category_id,
            fields=fields,
            timeout=settings.nova_check_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 — advisory; degrade, never 500
        await breaker.record_failure()
        logger.warning("player_check_failed", provider="nova",
                       category_id=target.category_id,
                       player_id_hash=hash_short(player_id), error=str(exc)[:200])
        return PlayerCheckOut(status="error")

    await breaker.record_success()
    out = _verdict(answer, target)
    if _worth_caching(out):
        with contextlib.suppress(Exception):  # cache is best-effort
            await get_redis().set(key, out.model_dump_json(), ex=_CACHE_TTL_SECONDS)
    logger.info("player_check", provider="nova", category_id=target.category_id,
                player_id_hash=hash_short(player_id), status=out.status)
    return out
```

`_verdict`:

```python
def _verdict(answer: NovaValidation, target: NovaValidateTarget) -> PlayerCheckOut:
    """Turn one NOVA answer into an advisory verdict.

    A negative becomes ``error``, not ``invalid``: see the module docstring.
    A positive whose region does not match the brand becomes ``error`` too —
    the same rule, applied to the one case where their answer may be about a
    different game client than the customer is buying for.
    """
    if not answer.valid:
        return PlayerCheckOut(status="error")
    if target.region_word:
        region = (answer.region or "").lower()
        if target.region_word not in region:
            logger.warning(
                "player_check_fallback_region_mismatch",
                provider="nova",
                category_id=target.category_id,
                expected=target.region_word,
                region=region[:32] or "(none)",
                hint="NOVA validated the id for a different region than this brand "
                "sells; answering `error` rather than confirming the wrong game",
            )
            return PlayerCheckOut(status="error")
    return PlayerCheckOut(status="valid", name=answer.player_name)
```

`fallback_for_steam` is the same shape over `check_steam_login`, with its own cache key and this docstring line: "`can_refill: false` is NOVA saying _they_ cannot refill that account — a weaker statement than 'no such login', and not one a customer may be shown as a rejection."

- [ ] **Step 4: Wire the two hooks into `player_check.py`**

In `check_player_for_brand_id`, after the `field is None` guard, read the slug **before** any supplier call (the session is about to be released for the round trip):

```python
    brand_slug = (
        await session.execute(select(Brand.slug).where(Brand.id == brand_id))
    ).scalar_one_or_none()
```

and route each provider's result through its fallback:

```python
    if field["check"]["provider"] == "waxpeer":
        await session.rollback()
        out = await _check_waxpeer_login(_waxpeer_fulfiller_or_none(), steam_login=player_id)
        return out if out.status != "error" else await _nova_steam(player_id)
    out = await _check_g2b_player(
        session, brand_id=brand_id, player_id=player_id, server_id=server_id
    )
    return out if out.status != "error" else await _nova_brand(brand_slug, player_id, server_id)
```

plus the two hooks, with the lazy import this module already uses for `routes`:

```python
async def _nova_brand(
    brand_slug: str | None, player_id: str, server_id: str | None
) -> PlayerCheckOut:
    """Second opinion when the primary could not answer. Never ``invalid``."""
    from yupay.modules.integrations.player_check_nova import fallback_for_brand

    return await fallback_for_brand(
        brand_slug=brand_slug, player_id=player_id, server_id=server_id
    )


async def _nova_steam(steam_login: str) -> PlayerCheckOut:
    """As :func:`_nova_brand`, for the Steam-login branch."""
    from yupay.modules.integrations.player_check_nova import fallback_for_steam

    return await fallback_for_steam(steam_login=steam_login)
```

Update the module docstring's first paragraph to say that an `error` from either provider is retried against NOVA, and that the fallback never returns `invalid`.

- [ ] **Step 5: Run the tests**

Run: `cd apps/api && uv run pytest tests/unit/test_player_check_nova.py tests -q -k "player_check"`
Expected: all pass, including the existing brand-check suite unchanged.

- [ ] **Step 6: Lint, typecheck, commit**

```bash
cd apps/api && uv run ruff format src/yupay/modules/integrations tests/unit/test_player_check_nova.py && uv run ruff check src/yupay/modules/integrations
# mypy runs from the REPO ROOT — see Task 2's note.
cd /Users/macbook_uz/Projects/yupay && uv run mypy apps/api/src/yupay/modules/integrations/player_check_nova.py apps/api/src/yupay/modules/integrations/player_check.py
git add apps/api/src/yupay/modules/integrations apps/api/tests/unit
git commit -m "feat(api/integrations): fall back to NOVA when the player check errors"
```

---

## Task 6: Admin supplier lists

**Files:**

- Modify: `apps/admin/src/features/integrations/types.ts` (lines ~158-275)
- Test: `apps/admin/src/features/integrations/SupplierDetailPage.test.tsx` or `MappingEditPage.test.tsx` — extend whichever already asserts the supplier list

**Interfaces:**

- Consumes: the slug `nova` from Task 2. Produces: nothing other tasks read.

- [ ] **Step 1: Add the slug everywhere the file enumerates suppliers**

```ts
export const KNOWN_SUPPLIERS = ["g2b", "waxpeer", "gengine", "nova"] as const;
```

plus the label (`nova: "NOVA"`), the capability entry (`nova: { catalogue: false }` — no catalogue browser in this branch), and the suppliers list entry:

```ts
  {
    slug: "nova",
    label: "NOVA",
    external: true,
    mappings: true,
    note: "резерв: пополнения игр",
  },
```

and a help string in the same map as `gengine`'s and `waxpeer`'s, in the same Russian register as its neighbours: NOVA is a reserve, an order goes there only when a SKU is switched to it by hand.

- [ ] **Step 2: Check for other enumerations**

Run: `rg -n "gengine" apps/admin/src apps/web/src | grep -v test`
Every list that names `gengine` as a real supplier either gains `nova` or gets a comment saying why not. `FulfillmentPage.tsx:39`'s comment about which suppliers produce tasks is one of them.

- [ ] **Step 3: Run the admin tests**

Run: `pnpm --filter @yupay/admin exec vitest run src/features/integrations`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add apps/admin/src
git commit -m "feat(admin/integrations): list NOVA as a mappable supplier"
```

---

## Task 7: Mapping seed

**Files:**

- Create: `scripts/seed/2026-09-17_nova_mappings.py`

**Interfaces:**

- Consumes: `NovaClient` (Task 1), `SkuSupplierMapping`.
- Produces: nothing code depends on. It is run by hand, inside the api container.

- [ ] **Step 1: Write the script**

A `python -` script in the shape of `scripts/seed/2026-09-03_steam_gifts.py` (read it first for the session bootstrap this repo uses). Behaviour:

```python
"""Match our SKUs to NOVA offers and write `nova` supplier mappings.

Run inside the api container so it can reach both the database and NOVA:

    docker compose -f docker-compose.prod.yml exec -T api \
        python - < scripts/seed/2026-09-17_nova_mappings.py

It matches on the denomination number only — `Sku.units` when set, otherwise
the leading integer of `Sku.denomination` or `sku_code` — and writes a mapping
only on an exact match. Everything it could not match is printed for an
operator to finish in the admin: guessing which of "275 Diamonds" and "275
Diamonds + Bonus" a SKU meant is not a thing a script should do with money.

Mappings are written ACTIVE. That is safe because sourcing picks the oldest
active mapping (see `sourcing.service._resolve_auto`), so an order keeps going
to the incumbent supplier until somebody sets `force_supplier = nova`.
"""

BRAND_CATEGORIES: dict[str, str] = {
    # our brand slug -> their TOP-UP category id (not the validate namespace)
    "mobile-legends-ru": "mobile_legends_ru",
    "mobile-legends": "mobile_legends_global",
    "pubg-mobile": "pubg_mobile_auto",
}
```

The matcher, in full — it is the part that must not be improvised:

```python
_NUM = re.compile(r"\d+")


def _amount_of(text: str | None) -> int | None:
    """The leading integer in a denomination label, or ``None``.

    "275 Diamonds" -> 275, "1800 UC" -> 1800, "Weekly Pass" -> None. A label
    with no number is never matched: two passes with no denomination are not
    the same product just because neither has a number.
    """
    if not text:
        return None
    m = _NUM.search(text)
    return int(m.group(0)) if m else None


def _sku_amount(sku: Any) -> int | None:
    """What this SKU sells, as a number. `units` first — it is the one field
    that was set on purpose — then the labels."""
    if sku.units:
        return int(sku.units)
    return _amount_of(sku.denomination) or _amount_of(sku.sku_code)
```

For each brand: load its active products' SKUs (`id`, `sku_code`, `denomination`, `units`,
`cost_usdt`), fetch `get_offers(category_id)`, and pair `_sku_amount(sku)` against
`_amount_of(offer["name"])` on equality. A number that matches **more than one** offer (their
"250 Coins" and "250 Coins + Epic Box" both parse to 250) is reported as unmatched, not guessed.
Upsert with `ON CONFLICT (sku_id, supplier_slug) DO UPDATE` setting `kind='game'`,
`external_product_id=category_id`, `external_variant_id=offer_id`, `is_active=true`,
`updated_by='seed:2026-09-17_nova_mappings'`. Print two tables — matched (`sku_code`, offer name,
our `cost_usdt`, their `price_usd`) and unmatched (`sku_code`, denomination, why) — then commit
once and print the counts.

Note in the file header that `pubg_mobile_auto` is one of four speed tiers (`_auto`, `_fast`, `_manual`, `_reserve`) and that the operator confirms the choice against the price table it prints.

- [ ] **Step 2: Dry-run it locally against the dev database**

Run: `make dev` (if not already up), then run the script inside the api container against the dev catalogue. If dev has no NOVA key, the fetch fails — that is the expected failure and the script must say so in one line rather than traceback.

- [ ] **Step 3: Commit**

```bash
git add scripts/seed/2026-09-17_nova_mappings.py
git commit -m "chore(seed): match our SKUs to NOVA offers and write nova mappings"
```

---

## Task 8: Documentation

**Files:**

- Create: `docs/decisions/0081-nova-reserve-supplier.md`, `docs/runbooks/nova.md`
- Modify: `docs/architecture/module-map.md`, `docs/architecture/cache-keys.md`, `docs/product/flows/player-check.md`, `apps/api/src/yupay/modules/fulfillment/README.md`, `apps/api/src/yupay/modules/sourcing/README.md`, `docs/runbooks/merchant-b2b.md`

- [ ] **Step 1: Write ADR-0081**

Use `docs/decisions/0000-template.md`. Status Accepted, date 2026-09-17, deciders owner + Claude, tags `backend | data`. It records four decisions and the reasons the design doc argues for each:

1. NOVA is a **reserve**, routed to only by an explicit `force_supplier` rule — no automatic supplier→supplier chain.
2. The player-check fallback **never answers `invalid`** (the ADR-0031 interaction is the whole reason).
3. The validate target is a **code table keyed by brand slug**, not a `sku_supplier_mapping` row — with the three concrete costs of the mapping route (the `kind` CHECK constraint, `_resolve_auto`'s kind-blind lookup, the admin wizard's kind coercion).
4. Auto sourcing picks the **oldest** active mapping, which is a behaviour change to an existing function and needs to be findable later.

Link ADR-0031 (advisory checks), ADR-0052 (G-Engine as a second source) and ADR-0079 (brand-level check).

- [ ] **Step 2: Write `docs/runbooks/nova.md`**

Sections, all of them operational:

- **What NOVA is for** — one paragraph: reserve for game top-ups, fallback for the check.
- **Funding** — the balance is USD/USDT; `GET /api/v2/balance` is the one-call health probe; a zero balance shows up as `supplier_low_balance` in the admin inbox with the customer still on "в обработке".
- **Switching a SKU to NOVA and back** — Sourcing → the SKU → `force_supplier = nova` (accepted only with an active mapping); tasks already failed elsewhere: inbox → task → «Сменить поставщика». The exact mirror of the Steam/G-Engine procedure.
- **The first live order (do this once, after funding)** — place one cheap order through a switched SKU, then record here: the real keys of their order object, the statuses it passed through, and whether a retry with the same `Idempotency-Key` returned the original order or a 409. Until that is written down, `nova.order_without_status` / `nova.order_without_id` warnings in the logs are the signal that our guesses were wrong.
- **The check fallback** — when it fires (primary `error` only), what it can answer (`valid` / `error`, never `invalid`), how to turn it off without touching top-ups (`NOVA_PLAYER_CHECK_ENABLED=false`), and how to turn everything off (clear `NOVA_API_KEY`).
- **What the logs say** — `nova.request`, `player_check` with `provider=nova`, `player_check_fallback_region_mismatch`, `player_check_fallback_short_circuited`, `nova_reconcile.tick`.
- **Rate limits** — they document one, on a Steam-gifts endpoint we do not call. Nothing on validate or order. If a 429 ever appears, the breaker is what absorbs it on the check path; the order path has no retry budget by design.

- [ ] **Step 3: The smaller doc edits**

- `docs/architecture/cache-keys.md`: `playercheck:nova:{category_id}:{server_id|-}:{hash}` and `playercheck:nova:steam:{hash}`, TTL 300 s, positive verdicts only, with a line on why the namespace is separate from `playercheck:g2b:`.
- `docs/product/flows/player-check.md`: the fallback in the sequence diagram (primary `error` → NOVA → `valid` or `error`) and a sentence on why no `invalid` edge exists.
- `docs/architecture/module-map.md`: `nova` beside the other suppliers, and `player_check_nova` under `integrations`.
- `fulfillment/README.md`: NOVA in the supplier table, with the one-line money rule (charges on create).
- `sourcing/README.md`: the oldest-mapping rule from Task 4, and `nova` in the `MAPPING_REQUIRED_SUPPLIERS` sentence.
- `docs/runbooks/merchant-b2b.md`: one line in the `validate/player` section — the check now survives a G2B outage for some brands, and can answer "could not check" where it once answered nothing.

- [ ] **Step 4: Check formatting and links**

Run: `npx prettier --check docs scripts` and `rg -n "0081|nova" docs/decisions/0081-nova-reserve-supplier.md | head`
Expected: clean; every ADR cross-link resolves to a file that exists.

- [ ] **Step 5: Commit**

```bash
git add docs apps/api/src/yupay/modules/fulfillment/README.md apps/api/src/yupay/modules/sourcing/README.md
git commit -m "docs: record NOVA as a reserve supplier and a check fallback"
```

---

## Final gate

After the last task, from the repo root:

```bash
make lint typecheck test
npx prettier --check .
```

`make test` runs both suites. Anything red is fixed in the branch, not deferred: the Definition of Done in AGENTS.md §14 is the bar, and a supplier adapter that is merged red is a supplier adapter that loses an order.

Then, and only then, `superpowers:finishing-a-development-branch`.
