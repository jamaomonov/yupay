"""InPay (inpay.uz) — second card acquirer for the UZ market.

UZS-only aggregator (Click/Payme/Uzcard/Humo behind one hosted checkout).
Flow:

1. ``GET /authorization`` with merchant_id + merchant_token → a 24h bearer
   token. We cache it on the gateway instance and refresh on expiry.
2. ``POST /create`` (Bearer header) → ``order_id`` + ``pay_url`` (our
   ``intent_url``); the customer pays on InPay's checkout.
3. InPay ``POST``s an **unsigned** callback to our ``callback_url``. Because
   there is no signature, ``verify_webhook`` does NOT trust the body — it
   re-fetches the authoritative status via ``GET /transactions`` before the
   service mutates any state (same "webhook is a signal" model as G2B).

InPay has no refund API (only authorization/create/transactions) — refunds are
issued manually in the InPay dashboard, so ``refund`` raises a clear error.

Secrets: ``inpay_merchant_token`` and the bearer token never reach logs
(redactor) and are sent only in request query/body/headers, never logged.
See ADR-0021.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

import httpx

from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.payments.gateways.base import (
    PaymentGateway,
    PaymentGatewayError,
    PaymentIntent,
    RefundResult,
    WebhookEvent,
    WebhookOutcome,
    to_wire_amount,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger("yupay.payments.inpay")

# InPay charges in so'm only; ``amount`` carries no currency and has a 1000 so'm
# floor (per the docs).
MIN_AMOUNT_UZS = Decimal("1000")
# Bearer token is valid 24h; refresh a little early.
_TOKEN_TTL_SECONDS = 23 * 3600


# ---------------------------------------------------------------------------
# HTTP client (pure I/O)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InpayCreateResult:
    order_id: str
    pay_url: str


class InpayClient:
    """Thin async wrapper around InPay's REST API. No business logic, no DB."""

    def __init__(
        self,
        *,
        merchant_id: str,
        merchant_token: str,
        base_url: str = "https://inpay.uz/api/v1",
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._merchant_id = merchant_id
        self._merchant_token = merchant_token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._client = client  # injected for tests; None ⇒ transient per request

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        bearer: str | None = None,
    ) -> dict[str, Any]:
        """Issue a request, retrying network / 5xx; raise on ``success: false``."""
        url = f"{self._base_url}{path}"
        headers = {"Accept": "application/json"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"

        delay = 0.5
        for attempt in range(self._max_retries + 1):
            try:
                if self._client is not None:
                    resp = await self._client.request(
                        method, url, params=params, json=json_body, headers=headers
                    )
                else:
                    async with httpx.AsyncClient(timeout=self._timeout) as c:
                        resp = await c.request(
                            method, url, params=params, json=json_body, headers=headers
                        )
            except httpx.RequestError as exc:
                log.warning("inpay.network_error", path=path, attempt=attempt, error=str(exc))
                if attempt >= self._max_retries:
                    raise PaymentGatewayError(f"inpay network error: {exc}") from exc
                await asyncio.sleep(delay)
                delay *= 2
                continue

            # Never log query/body — they carry merchant_token / bearer.
            log.info("inpay.request", path=path, status=resp.status_code, attempt=attempt)

            if resp.status_code >= 500:
                if attempt >= self._max_retries:
                    raise PaymentGatewayError(f"inpay upstream error: HTTP {resp.status_code}")
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if resp.status_code >= 400:
                raise PaymentGatewayError(f"inpay HTTP {resp.status_code}: {resp.text[:200]}")

            try:
                data: dict[str, Any] = resp.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise PaymentGatewayError(f"inpay: non-JSON response: {exc}") from exc

            if data.get("success") is False:
                msg = data.get("message") or data.get("error") or "unknown error"
                raise PaymentGatewayError(f"inpay error: {msg}")
            return data

        raise PaymentGatewayError(f"inpay unreachable after {self._max_retries + 1} attempts")

    async def authorize(self) -> str:
        data = await self._request(
            "GET",
            "/authorization/",
            params={"merchant_id": self._merchant_id, "merchant_token": self._merchant_token},
        )
        token = data.get("bearer_token")
        if not token:
            raise PaymentGatewayError("inpay authorization: missing bearer_token")
        return str(token)

    async def create(
        self,
        *,
        bearer: str,
        amount: Decimal,
        description: str,
        callback_url: str,
        phone: str | None = None,
    ) -> InpayCreateResult:
        body: dict[str, Any] = {
            "merchant_id": self._merchant_id,
            "token": self._merchant_token,
            "amount": to_wire_amount(amount),
            "description": description,
            "callback_url": callback_url,
        }
        if phone:
            body["phone"] = phone
        data = await self._request("POST", "/create/", json_body=body, bearer=bearer)
        order_id = data.get("order_id")
        pay_url = data.get("pay_url")
        if not order_id or not pay_url:
            raise PaymentGatewayError("inpay create: missing order_id / pay_url")
        return InpayCreateResult(order_id=str(order_id), pay_url=str(pay_url))

    async def get_status(self, *, bearer: str, order_id: str) -> str:
        data = await self._request(
            "GET", "/transactions/", params={"order_id": order_id}, bearer=bearer
        )
        status = data.get("status")
        if not status:
            raise PaymentGatewayError("inpay transactions: missing status")
        return str(status)


# ---------------------------------------------------------------------------
# Gateway (protocol implementation)
# ---------------------------------------------------------------------------


def _map_status(status: str) -> WebhookOutcome:
    s = status.lower()
    if s == "success":
        return "succeeded"
    if s == "cancelled":
        return "cancelled"
    if s == "failed":
        return "failed"
    # pending / anything unknown → no-op; wait for the terminal callback.
    return "pending"


class InpayGateway(PaymentGateway):
    """``PaymentGateway`` for InPay's hosted checkout (UZS only)."""

    provider = "inpay"

    def __init__(self, client: InpayClient | None = None) -> None:
        # ``client`` injectable for tests; in prod we build a transient one per
        # call so a hot-reloaded credential is picked up.
        self._client_override = client
        # 24h bearer token cached on the singleton gateway instance.
        self._bearer: str | None = None
        self._bearer_exp: float = 0.0

    def _client(self) -> InpayClient:
        if self._client_override is not None:
            return self._client_override
        s = get_settings()
        return InpayClient(
            merchant_id=s.inpay_merchant_id,
            merchant_token=s.inpay_merchant_token,
            base_url=s.inpay_base_url,
            timeout_seconds=s.inpay_request_timeout_seconds,
        )

    async def _ensure_token(self, client: InpayClient) -> str:
        now_m = time.monotonic()
        if self._bearer and now_m < self._bearer_exp:
            return self._bearer
        token = await client.authorize()
        self._bearer = token
        self._bearer_exp = now_m + _TOKEN_TTL_SECONDS
        return token

    @property
    def available(self) -> bool:
        s = get_settings()
        return bool(s.inpay_merchant_id and s.inpay_merchant_token)

    async def create_intent(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002 -- InPay keeps no DB-side state at intent time
        order: Any,
        return_url: str,  # noqa: ARG002 -- InPay has no per-request return_url field
    ) -> PaymentIntent:
        if not self.available:
            raise PaymentGatewayError("inpay is not configured")
        s = get_settings()
        currency = (order.currency or "").upper()
        if currency != "UZS":
            raise PaymentGatewayError(f"inpay only charges in UZS; order currency is {currency!r}")
        amount: Decimal = order.total_charged
        if amount is None:
            raise PaymentGatewayError("order total_charged is missing")
        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if amount < MIN_AMOUNT_UZS:
            raise PaymentGatewayError(f"inpay minimum amount is {MIN_AMOUNT_UZS} UZS")

        callback_url = f"{s.base_url.rstrip('/')}/api/v1/webhooks/payments/inpay"
        client = self._client()
        bearer = await self._ensure_token(client)
        result = await client.create(
            bearer=bearer,
            amount=amount,
            description=f"YuPay order {order.id}",
            callback_url=callback_url,
        )
        log.info("inpay.intent.created", order_id=order.id, inpay_order_id=result.order_id)
        return PaymentIntent(
            external_id=result.order_id,
            intent_url=result.pay_url,
            status="pending",
            extra_metadata={"inpay_order_id": result.order_id},
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],  # noqa: ARG002 -- InPay sends no auth headers
        body: bytes,
    ) -> WebhookEvent:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PaymentGatewayError(f"inpay webhook: invalid body: {exc}") from exc
        if not isinstance(payload, dict):
            raise PaymentGatewayError("inpay webhook: body is not a JSON object")
        order_id = str(payload.get("order_id") or "")
        if not order_id:
            raise PaymentGatewayError("inpay webhook: missing order_id")

        # InPay does not sign callbacks — never trust the body's ``status``.
        # Re-fetch the authoritative status from /transactions before the
        # service touches any state. A forged callback for a real order_id
        # can't promote a payment unless InPay itself reports success.
        if not self.available:
            raise PaymentGatewayError("inpay is not configured; cannot verify webhook")
        client = self._client()
        bearer = await self._ensure_token(client)
        verified_status = await client.get_status(bearer=bearer, order_id=order_id)

        return WebhookEvent(
            external_event_id=f"{order_id}:{verified_status}",
            external_payment_id=order_id,
            outcome=_map_status(verified_status),
            raw={**payload, "_verified_status": verified_status},
        )

    async def refund(
        self,
        *,
        payment: Any,  # noqa: ARG002
        amount: Decimal,  # noqa: ARG002
    ) -> RefundResult:
        # InPay exposes no refund API (authorization/create/transactions only).
        raise PaymentGatewayError(
            "InPay has no refund API — issue the refund from the InPay merchant dashboard"
        )


__all__ = [
    "InpayClient",
    "InpayCreateResult",
    "InpayGateway",
]
