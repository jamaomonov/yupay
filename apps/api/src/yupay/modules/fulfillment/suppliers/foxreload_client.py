"""HTTP client for FoxReload's public wholesale API (public-api.foxreload.com).

Read off their OpenAPI document (``/openapi.json``, v1.0.0) on 2026-11-24.
What this integration relies on:

* **Auth** is one ``X-API-Key`` header. A key may carry an IP allowlist; a call
  from elsewhere answers 403.
* **Currency** comes from ``X-Currency`` on the *create*: the order keeps it,
  and ``/pay`` debits the balance in that currency. We always send ``usd``.
* **An order is two calls.** ``POST /api/orders/`` creates it unpaid
  (``active``); ``POST /api/orders/{id}/pay`` with no body debits our balance.
  Nothing is bought until the second call succeeds.
* **``idempotencyKey`` is refused on reuse, not replayed**: a second create
  under the same key answers 400 ``ORDER_ALREADY_EXISTS``. The order is then
  found with ``GET /api/orders/?idempotencyKey=…``. That lookup is what makes a
  timed-out create safe to repeat.
* **Errors** are ``{"detail", "code"}``. 429 carries ``Retry-After``.
* **A failed item refunds itself**: the order goes ``failed`` and, being
  wholesale, ``refunded`` right after, with ``items[].error`` worded for the
  end customer.

PII: the Steam login travels in the item's ``note`` (it has to) and is never
logged here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from yupay.core.logging import get_logger

log = get_logger("yupay.fulfillment.foxreload")

ORDER_ALREADY_EXISTS = "ORDER_ALREADY_EXISTS"
BALANCE_NOT_ENOUGH = "BALANCE_NOT_ENOUGH"
ORDER_PAYMENT_ALREADY_CREATED = "ORDER_PAYMENT_ALREADY_CREATED"

#: The currency every order is created (and so paid) in.
CURRENCY = "usd"


class FoxreloadError(Exception):
    """FoxReload answered and refused the call (a 4xx with their error body).

    Args:
        status: The HTTP status.
        code: Their machine-readable ``code``, or ``""`` when absent.
        detail: Their ``detail`` text, trimmed. Never carries the login: their
            errors name fields, not values.
    """

    def __init__(self, *, status: int, code: str, detail: str) -> None:
        super().__init__(f"foxreload HTTP {status} {code}: {detail}")
        self.status = status
        self.code = code
        self.detail = detail


class FoxreloadUnavailableError(Exception):
    """No usable answer: transport failure, timeout, 429, 5xx or an unreadable
    body. Whether the call took effect is unknown."""


@dataclass(frozen=True)
class FoxItem:
    """One order line, as much of it as we act on."""

    status: str
    error: str | None


@dataclass(frozen=True)
class FoxOrder:
    """One FoxReload order."""

    id: str
    status: str
    price: Decimal | None
    refunded_amount: Decimal | None
    items: tuple[FoxItem, ...]

    @property
    def item_error(self) -> str | None:
        """The first item's customer-facing error, if any."""
        return next((i.error for i in self.items if i.error), None)


def _decimal(raw: Any) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return None


def order_of(body: Any) -> FoxOrder:
    """Parse an ``OrderOut``. Raises ``FoxreloadUnavailableError`` on a body
    without an id or status: acting on half an order is worse than asking
    again."""
    if not isinstance(body, dict) or not body.get("id") or not body.get("status"):
        raise FoxreloadUnavailableError("foxreload order body without id/status")
    items = tuple(
        FoxItem(
            status=str(i.get("fulfillmentStatus") or ""),
            error=(str(i["error"]) if i.get("error") else None),
        )
        for i in (body.get("items") or [])
        if isinstance(i, dict)
    )
    return FoxOrder(
        id=str(body["id"]),
        status=str(body["status"]),
        price=_decimal(body.get("price")),
        refunded_amount=_decimal(body.get("refundedAmount")),
        items=items,
    )


class FoxreloadClient:
    """Thin async client over the endpoints this integration calls."""

    def __init__(self, *, api_key: str, base_url: str, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        headers = {"X-API-Key": self._api_key, "X-Currency": CURRENCY, "X-Language": "ru"}
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
                resp = await client.request(method, path, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise FoxreloadUnavailableError(f"{method} {path}: {type(exc).__name__}") from exc
        if resp.status_code == 429 or resp.status_code >= 500:
            raise FoxreloadUnavailableError(f"{method} {path}: HTTP {resp.status_code}")
        try:
            body = resp.json() if resp.content else None
        except ValueError as exc:
            raise FoxreloadUnavailableError(f"{method} {path}: unreadable body") from exc
        if resp.is_success:
            return body
        code = str(body.get("code") or "") if isinstance(body, dict) else ""
        detail = body.get("detail") if isinstance(body, dict) else None
        raise FoxreloadError(
            status=resp.status_code,
            code=code,
            detail=str(detail if isinstance(detail, str) else "")[:200],
        )

    async def create_order(
        self, *, product_id: str, quantity: int, login: str, idempotency_key: str
    ) -> FoxOrder:
        """Create an unpaid order for ``quantity`` units of one product.

        Args:
            product_id: Their product id (``itemId``).
            quantity: Whole units within the product's order bounds.
            login: The Steam login, sent as the ``login`` note field. Never logged.
            idempotency_key: Unique per order on their side; a reuse answers
                ``ORDER_ALREADY_EXISTS``.
        """
        body = await self._request(
            "POST",
            "/api/orders/",
            json={
                "items": [
                    {"itemId": product_id, "quantity": int(quantity), "note": {"login": login}}
                ],
                "idempotencyKey": idempotency_key,
            },
        )
        return order_of(body)

    async def pay_order(self, order_id: str) -> None:
        """Pay an order from our balance, in the order's currency."""
        await self._request("POST", f"/api/orders/{order_id}/pay")

    async def get_order(self, order_id: str) -> FoxOrder:
        """One order with its items."""
        return order_of(await self._request("GET", f"/api/orders/{order_id}"))

    async def find_order_id(self, idempotency_key: str) -> str | None:
        """The id of the order created under ``idempotency_key``, or ``None``."""
        body = await self._request(
            "GET", "/api/orders/", params={"idempotencyKey": idempotency_key, "limit": 1}
        )
        items = body.get("items") if isinstance(body, dict) else body
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            return None
        found = items[0].get("id")
        return str(found) if found else None

    async def usd_balance(self) -> Decimal | None:
        """Our available USD balance, or ``None`` when they hold none in USD."""
        body = await self._request("GET", "/api/access/me/balances/")
        for row in body if isinstance(body, list) else []:
            if isinstance(row, dict) and str(row.get("currency")) == CURRENCY:
                return _decimal(row.get("available"))
        return None


__all__ = [
    "BALANCE_NOT_ENOUGH",
    "CURRENCY",
    "ORDER_ALREADY_EXISTS",
    "ORDER_PAYMENT_ALREADY_CREATED",
    "FoxItem",
    "FoxOrder",
    "FoxreloadClient",
    "FoxreloadError",
    "FoxreloadUnavailableError",
    "order_of",
]
