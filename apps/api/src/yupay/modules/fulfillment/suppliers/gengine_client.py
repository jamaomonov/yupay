"""HTTP client for G-Engine's v2.1 API (api.g-engine.net).

Transport only: it speaks the wire format and raises on refusals. Order state
interpretation lives in the fulfiller that wraps this client.

Four things about this API drive the shape below, all verified against the
live service:

* Auth is an ``X-API-Key`` header. Without it every call is a flat ``401``.
* **Two different response envelopes coexist.** ``/users/balance`` and
  ``/shop/*`` wrap their payload in ``{"success", "message", "data"}``, while
  ``/recharge/*`` returns the object directly. ``_unwrap`` handles both rather
  than making every call site remember which is which.
* ``limit`` is capped at 100 server-side; asking for more is a ``success:
  false`` refusal, not a clamp. :data:`MAX_PAGE` mirrors the cap so we never
  spend a round trip learning it.
* A recharge order is created **unpaid**. G-Engine verifies the account
  itself, and only an order that reached ``verified`` may be paid — which is
  why the fulfiller drives it as a state machine instead of one call.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from yupay.core.logging import get_logger

log = get_logger("yupay.fulfillment.gengine")

#: The server's own ceiling on ``limit``.
MAX_PAGE = 100

#: Statuses a recharge order moves through. ``verified`` is the one that opens
#: payment; ``invalid_account`` is the customer's mistake, not ours.
GEngineOrderStatus = Literal[
    "pending",
    "processing",
    "verified",
    "paid",
    "shipped",
    "cancelled",
    "invalid_account",
    "invalid_amount",
]

#: Parameter names the API accepts per service (``GET /recharge/services``
#: reports which of them a given service needs).
GEngineParamKey = Literal["Account", "Server", "Region", "Quantity"]


class GEngineError(Exception):
    """G-Engine refused the call (transport fine, business failure).

    ``body`` carries the raw response text for the same reason the G2B and
    Waxpeer clients keep it: a caller sometimes has to re-read the payload to
    tell a real fault from a legitimate verdict.
    """

    def __init__(self, message: str, *, status: int = 200, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class GEngineUnavailableError(Exception):
    """G-Engine could not be reached at all (network error, timeout, DNS)."""


@dataclass(frozen=True)
class GEngineOrder:
    """One recharge order as G-Engine reports it."""

    id: int
    uuid: str
    status: str
    price: float
    currency: str | None
    is_refunded: bool


def _unwrap(body: Any) -> Any:
    """Return the payload, whichever envelope it arrived in.

    ``{"success": false, "message": ...}`` is a refusal even on HTTP 200, so
    it raises rather than being handed back as data — the status code alone
    never tells you whether a call worked.
    """
    if not isinstance(body, dict):
        return body
    if "success" in body:
        if not body.get("success"):
            raise GEngineError(
                str(body.get("message") or "g-engine refused the call"),
                status=200,
                body=str(body)[:500],
            )
        return body.get("data")
    return body


class GEngineClient:
    """Thin async client. One instance per call site; cheap to construct."""

    def __init__(self, *, api_key: str, base_url: str, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    @contextlib.asynccontextmanager
    async def _session(self) -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={"X-API-Key": self._api_key, "Accept": "application/json"},
        ) as client:
            yield client

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with self._session() as client:
                resp = await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            # Network-level: nothing was decided upstream, so this is ours to
            # retry — distinct from a refusal, which is upstream's answer.
            raise GEngineUnavailableError(str(exc)) from exc

        text = resp.text[:500]
        log.info("gengine.request", method=method, path=path, status=resp.status_code)
        if resp.status_code >= 400:
            raise GEngineError(
                f"g-engine HTTP {resp.status_code}", status=resp.status_code, body=text
            )
        try:
            body = resp.json()
        except ValueError as exc:
            raise GEngineError(
                "g-engine returned non-JSON", status=resp.status_code, body=text
            ) from exc
        return _unwrap(body)

    # ---------- probes ----------

    async def health(self) -> dict[str, Any]:
        """``GET /health`` — reachability plus API-key validity in one call."""
        body: dict[str, Any] = await self._request("GET", "/health")
        return body

    async def get_balance(self) -> dict[str, Any]:
        """Wallet balance. Returns ``{balance, cashback, currency}``."""
        data: dict[str, Any] = await self._request("GET", "/users/balance")
        return data or {}

    # ---------- catalogue ----------

    async def list_recharge_services(
        self, *, limit: int = MAX_PAGE, offset: int = 0
    ) -> list[dict[str, Any]]:
        """One page of top-up services, each with its denominations and the
        parameter keys it requires (``Account`` / ``Server`` / ``Region`` /
        ``Quantity``)."""
        body = await self._request(
            "GET",
            "/recharge/services",
            params={"limit": min(limit, MAX_PAGE), "offset": offset},
        )
        items = body.get("items") if isinstance(body, dict) else body
        return [i for i in (items or []) if isinstance(i, dict)]

    # ---------- ordering ----------

    async def create_recharge_order(
        self,
        *,
        service_id: int,
        params: dict[str, str],
        denomination_id: int | None = None,
        uuid: str | None = None,
    ) -> GEngineOrder:
        """Create (but do not pay) a top-up order.

        ``uuid`` is ours to choose and is what makes a retry safe: the same
        value can be looked up with :meth:`get_recharge_order_by_uuid` instead
        of creating a second order for one sale.
        """
        payload: dict[str, Any] = {
            "params": [{"param_key": k, "param_value": v} for k, v in params.items()],
        }
        if denomination_id is not None:
            payload["denomination_id"] = denomination_id
        if uuid is not None:
            payload["uuid"] = uuid
        body = await self._request("POST", f"/recharge/orders/{service_id}", json=payload)
        return _to_order(body)

    async def pay_recharge_order(self, order_id: int) -> GEngineOrder:
        """Pay a ``verified`` order from the G-Engine wallet."""
        body = await self._request("POST", f"/recharge/orders/{order_id}/pay")
        return _to_order(body)

    async def get_recharge_order(self, order_id: int) -> GEngineOrder:
        body = await self._request("GET", f"/recharge/orders/{order_id}")
        return _to_order(body)

    async def get_recharge_order_by_uuid(self, uuid: str) -> GEngineOrder:
        """Look a sale up by the id we minted — the recovery path when a
        create call's response was lost."""
        body = await self._request("GET", f"/recharge/orders/{uuid}/uuid")
        return _to_order(body)


def _to_order(body: Any) -> GEngineOrder:
    if not isinstance(body, dict) or body.get("id") is None:
        raise GEngineError("g-engine returned no order", body=str(body)[:500])
    return GEngineOrder(
        id=int(body["id"]),
        uuid=str(body.get("uuid") or ""),
        status=str(body.get("status") or "unknown"),
        price=float(body.get("price") or 0),
        currency=(str(body["currency"]) if body.get("currency") else None),
        is_refunded=bool(body.get("is_refunded")),
    )


__all__ = [
    "MAX_PAGE",
    "GEngineClient",
    "GEngineError",
    "GEngineOrder",
    "GEngineOrderStatus",
    "GEngineParamKey",
    "GEngineUnavailableError",
]
