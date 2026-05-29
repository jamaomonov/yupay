"""Octo (octo.uz) — first real card acquirer for the UZ market.

Hosted payment page, one-stage (``auto_capture=true``): we ``POST /prepare_payment``,
hand the customer the returned ``octo_pay_url``, and Octo ``POST``s a signed callback
to our ``notify_url``. The signature lives in the body (not headers), so this gateway
plugs straight into the generic ``/webhooks/payments/{provider}`` flow — no dedicated
webhook route. See ADR-0020.

Secrets / PII policy:
- ``octo_shop_id`` / ``octo_secret`` go only in the JSON request body; we never log the
  body (the structured-log redactor also blocks ``octo_secret`` / ``octo_signature_key``).
- The callback Octo sends back may carry a *masked* PAN + ``rrn``; that lands in the
  admin-only ``PaymentWebhook.payload`` audit row but never in INFO logs. Octo never
  sends a full PAN.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

import httpx

from yupay.core.clock import now
from yupay.core.config import get_settings
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.payments.gateways.base import (
    PaymentGateway,
    PaymentGatewayError,
    PaymentIntent,
    RefundResult,
    WebhookEvent,
    WebhookOutcome,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger("yupay.payments.octo")

# Octo accepts these three on prepare_payment. An order in any other currency
# can't be charged via Octo — the gateway refuses with a clear message.
SUPPORTED_CURRENCIES = frozenset({"UZS", "USD", "RUB"})


# ---------------------------------------------------------------------------
# HTTP client (pure I/O)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OctoPrepareResult:
    octo_payment_uuid: str
    pay_url: str
    status: str


@dataclass(frozen=True)
class OctoRefundResult:
    refund_id: str
    status: str


class OctoClient:
    """Thin async wrapper around Octo's REST API. No business logic, no DB."""

    def __init__(
        self,
        *,
        shop_id: str,
        secret: str,
        base_url: str = "https://secure.octo.uz",
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._shop_id = shop_id
        self._secret = secret
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._client = client  # injected for tests; None ⇒ transient per request

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST with creds injected. Retries network / 5xx; raises on ``error != 0``.

        Both ``prepare_payment`` (keyed by ``shop_transaction_id``) and ``refund``
        (keyed by ``shop_refund_id``) are idempotent upstream, so retrying is safe.
        """
        url = f"{self._base_url}{path}"
        # ``octo_shop_id`` is typed Long by Octo; send numeric when it parses,
        # else as-is so an opaque id still works.
        shop_id: Any = self._shop_id
        with contextlib.suppress(TypeError, ValueError):
            shop_id = int(self._shop_id)
        body = {"octo_shop_id": shop_id, "octo_secret": self._secret, **payload}

        delay = 0.5
        for attempt in range(self._max_retries + 1):
            try:
                if self._client is not None:
                    resp = await self._client.post(url, json=body)
                else:
                    async with httpx.AsyncClient(timeout=self._timeout) as c:
                        resp = await c.post(url, json=body)
            except httpx.RequestError as exc:
                log.warning("octo.network_error", path=path, attempt=attempt, error=str(exc))
                if attempt >= self._max_retries:
                    raise PaymentGatewayError(f"octo network error: {exc}") from exc
                await asyncio.sleep(delay)
                delay *= 2
                continue

            # Never log ``body`` — it carries the secret.
            log.info("octo.request", path=path, status=resp.status_code, attempt=attempt)

            if resp.status_code >= 500:
                if attempt >= self._max_retries:
                    raise PaymentGatewayError(f"octo upstream error: HTTP {resp.status_code}")
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if resp.status_code >= 400:
                raise PaymentGatewayError(f"octo HTTP {resp.status_code}: {resp.text[:200]}")

            try:
                data: dict[str, Any] = resp.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise PaymentGatewayError(f"octo: non-JSON response: {exc}") from exc

            error = data.get("error")
            if error not in (0, None):
                msg = data.get("errMessage") or data.get("errorMessage") or "unknown error"
                raise PaymentGatewayError(f"octo error {error}: {msg}")
            return data

        raise PaymentGatewayError(f"octo unreachable after {self._max_retries + 1} attempts")

    async def prepare_payment(
        self,
        *,
        shop_transaction_id: str,
        total_sum: Decimal,
        currency: str,
        description: str,
        return_url: str,
        notify_url: str,
        init_time: str,
        auto_capture: bool = True,
        test: bool = False,
        language: str = "ru",
        ttl: int = 15,
    ) -> OctoPrepareResult:
        payload: dict[str, Any] = {
            "shop_transaction_id": shop_transaction_id,
            "auto_capture": auto_capture,
            "init_time": init_time,
            "test": test,
            "total_sum": float(total_sum),
            "currency": currency,
            "description": description,
            "return_url": return_url,
            "notify_url": notify_url,
            "language": language,
            "ttl": ttl,
        }
        data = await self._post("/prepare_payment", payload)
        d = data.get("data") or data
        pay_url = d.get("octo_pay_url")
        uuid = d.get("octo_payment_UUID")
        if not pay_url or not uuid:
            raise PaymentGatewayError(
                "octo prepare_payment: missing octo_pay_url / octo_payment_UUID"
            )
        return OctoPrepareResult(
            octo_payment_uuid=str(uuid),
            pay_url=str(pay_url),
            status=str(d.get("status") or "created"),
        )

    async def refund(
        self,
        *,
        octo_payment_uuid: str,
        shop_refund_id: str,
        amount: Decimal,
    ) -> OctoRefundResult:
        data = await self._post(
            "/refund",
            {
                "octo_payment_UUID": octo_payment_uuid,
                "shop_refund_id": shop_refund_id,
                "amount": float(amount),
            },
        )
        d = data.get("data") or data
        refund_id = d.get("refund_id")
        if not refund_id:
            raise PaymentGatewayError("octo refund: missing refund_id")
        return OctoRefundResult(
            refund_id=str(refund_id), status=str(d.get("status") or "succeeded")
        )


# ---------------------------------------------------------------------------
# Gateway (protocol implementation)
# ---------------------------------------------------------------------------


def compute_signature(unique_key: str, octo_payment_uuid: str, status: str) -> str:
    """``SHA1(unique_key + octo_payment_UUID + status)`` as lowercase hex.

    Octo's docs show the signature as 40-char uppercase hex; we compare
    case-insensitively (both sides lowercased) in :meth:`OctoGateway.verify_webhook`.
    """
    # SHA1 is mandated by Octo's webhook signature scheme — not our choice, and
    # used only to authenticate their callback, not to protect data at rest.
    digest = hashlib.sha1(  # noqa: S324
        f"{unique_key}{octo_payment_uuid}{status}".encode()
    )
    return digest.hexdigest()


def _map_status(status: str) -> WebhookOutcome:
    s = status.lower()
    if s == "succeeded":
        return "succeeded"
    if s in {"canceled", "cancelled"}:
        return "cancelled"
    if s in {"failed", "expired", "declined"}:
        return "failed"
    # created / wait_user_action / waiting_for_capture / anything unknown →
    # signed-but-not-terminal: record for audit, don't move the FSM.
    return "pending"


class OctoGateway(PaymentGateway):
    """``PaymentGateway`` for the Octo hosted payment page (one-stage)."""

    provider = "octo"

    def __init__(self, client: OctoClient | None = None) -> None:
        # ``client`` injectable for tests; in prod we build a transient one per
        # call so a hot-reloaded credential is picked up.
        self._client_override = client

    def _client(self) -> OctoClient:
        if self._client_override is not None:
            return self._client_override
        s = get_settings()
        return OctoClient(
            shop_id=s.octo_shop_id,
            secret=s.octo_secret,
            base_url=s.octo_base_url,
            timeout_seconds=s.octo_request_timeout_seconds,
        )

    @property
    def available(self) -> bool:
        s = get_settings()
        return bool(s.octo_shop_id and s.octo_secret)

    async def create_intent(
        self,
        *,
        db: AsyncSession,  # noqa: ARG002 -- Octo keeps no DB-side state at intent time
        order: Any,
        return_url: str,
    ) -> PaymentIntent:
        if not self.available:
            raise PaymentGatewayError("octo is not configured")
        s = get_settings()
        currency = (order.currency or "").upper()
        if currency not in SUPPORTED_CURRENCIES:
            raise PaymentGatewayError(
                f"octo does not support currency {currency!r}; supported: UZS, USD, RUB"
            )
        amount: Decimal = order.total_charged
        if amount is None or amount <= 0:
            raise PaymentGatewayError("order total_charged is non-positive")
        # Octo wants major units (e.g. 1000.0 UZS). ``total_charged`` is already
        # in the order's major units (orders/service.py), so just quantize.
        total_sum = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Fresh per prepare — a previous failed attempt's id can't clash upstream.
        shop_transaction_id = new_id()
        notify_url = f"{s.base_url.rstrip('/')}/api/v1/webhooks/payments/octo"

        result = await self._client().prepare_payment(
            shop_transaction_id=shop_transaction_id,
            total_sum=total_sum,
            currency=currency,
            description=f"YuPay order {order.id}",
            return_url=return_url or s.telegram_miniapp_url,
            notify_url=notify_url,
            init_time=now().strftime("%Y-%m-%d %H:%M:%S"),
            auto_capture=True,
            test=s.octo_test_mode,
        )
        log.info(
            "octo.intent.created",
            order_id=order.id,
            octo_payment_uuid=result.octo_payment_uuid,
            octo_status=result.status,
            test=s.octo_test_mode,
        )
        return PaymentIntent(
            external_id=result.octo_payment_uuid,
            intent_url=result.pay_url,
            status="pending",
            extra_metadata={
                "shop_transaction_id": shop_transaction_id,
                "octo_status": result.status,
                "test": s.octo_test_mode,
            },
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],  # noqa: ARG002 -- Octo signs in the body
        body: bytes,
    ) -> WebhookEvent:
        s = get_settings()
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PaymentGatewayError(f"octo webhook: invalid body: {exc}") from exc
        if not isinstance(payload, dict):
            raise PaymentGatewayError("octo webhook: body is not a JSON object")

        # Never accept a callback we can't verify. In prod this is a hard stop;
        # the key is issued by Octo tech support out-of-band.
        if not s.octo_signature_key:
            raise PaymentGatewayError("octo signature key not configured; refusing webhook")

        uuid = str(payload.get("octo_payment_UUID") or "")
        status = str(payload.get("status") or "")
        signature = str(payload.get("signature") or "")
        if not uuid or not status:
            raise PaymentGatewayError("octo webhook: missing octo_payment_UUID or status")

        expected = compute_signature(s.octo_signature_key, uuid, status)
        if not hmac.compare_digest(expected, signature.lower()):
            raise PaymentGatewayError("octo webhook: signature mismatch")

        return WebhookEvent(
            # One event per (payment, status): replays of the same status dedup,
            # distinct statuses (e.g. created → succeeded) stay separate events.
            external_event_id=f"{uuid}:{status}",
            external_payment_id=uuid,
            outcome=_map_status(status),
            raw=payload,
        )

    async def refund(
        self,
        *,
        payment: Any,
        amount: Decimal,
    ) -> RefundResult:
        if not self.available:
            raise PaymentGatewayError("octo is not configured")
        if amount <= 0:
            raise PaymentGatewayError("refund amount must be positive")
        octo_payment_uuid = getattr(payment, "external_id", None)
        if not octo_payment_uuid:
            raise PaymentGatewayError("payment has no octo_payment_UUID to refund")
        shop_refund_id = new_id()
        result = await self._client().refund(
            octo_payment_uuid=octo_payment_uuid,
            shop_refund_id=shop_refund_id,
            amount=amount,
        )
        return RefundResult(
            external_refund_id=result.refund_id,
            amount=amount,
            extra_metadata={"shop_refund_id": shop_refund_id, "octo_status": result.status},
        )


__all__ = [
    "OctoClient",
    "OctoGateway",
    "OctoPrepareResult",
    "OctoRefundResult",
    "compute_signature",
]
