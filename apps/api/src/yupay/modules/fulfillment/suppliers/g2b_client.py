"""Thin async HTTP wrapper around the G2Bulk REST API.

Pure I/O — no business logic, no DB. The :class:`G2bFulfiller` in
``g2b.py`` is what calls this and translates the responses into
``FulfillResult`` / ``FulfillStatus``.

Auth: ``X-API-Key`` header. Idempotency: caller passes
``X-Idempotency-Key`` (always the YuPay ``task.id``).

Retry policy: 429 / 5xx are retryable with exponential backoff. 4xx other
than 429 are terminal and raise immediately — repeated 401s in particular
will get our IP permanently banned by G2B (see
``docs/g2b-intergation.md`` §10). 410 on the voucher delivery endpoint
means the order has failed / been refunded — treat as terminal-failed.
"""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from yupay.core.errors import UpstreamUnavailableError
from yupay.core.logging import get_logger

log = get_logger("yupay.fulfillment.g2b")

VoucherOutcome = Literal["completed", "pending", "failed"]


class G2bError(Exception):
    """G2B returned a non-recoverable 4xx (other than 429)."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"g2b error: HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


class G2bTerminalError(Exception):
    """G2B reported the order as FAILED/REFUNDED/CANCELLED (HTTP 410)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


# Back-compat alias for callers that want the more readable name.
G2bTerminalFailure = G2bTerminalError


@dataclass(frozen=True)
class VoucherPurchaseResult:
    g2b_order_id: str
    status: VoucherOutcome
    delivery_items: list[str] | None  # codes (present iff status == 'completed')


@dataclass(frozen=True)
class VoucherDeliveryResult:
    status: VoucherOutcome
    delivery_items: list[str] | None


@dataclass(frozen=True)
class GameOrderCreated:
    g2b_order_id: str
    status: Literal["pending", "processing", "completed", "failed"]


@dataclass(frozen=True)
class GameOrderStatus:
    g2b_order_id: str
    status: Literal["pending", "processing", "completed", "failed"]
    message: str | None


class G2bClient:
    """Async client. Single shared instance per process is fine — httpx
    pools connections internally."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 20.0,
        max_retries: int = 4,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._client = client  # for tests; None ⇒ transient per request

    # ---------- core request ----------

    @asynccontextmanager
    async def _http(self):  # type: ignore[no-untyped-def]
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            yield c

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        treat_410_as: Literal["error", "terminal_failure"] = "error",
    ) -> httpx.Response:
        """Issue a request with retry on 429/5xx and a fail-fast on 401/400."""
        url = f"{self._base_url}{path}"
        headers = {"X-API-Key": self._api_key}
        if idempotency_key is not None:
            headers["X-Idempotency-Key"] = idempotency_key

        delay = 1.0
        last_status = 0
        for attempt in range(self._max_retries + 1):
            async with self._http() as client:
                try:
                    resp: httpx.Response = await client.request(
                        method, url, json=json, headers=headers
                    )
                except httpx.RequestError as exc:
                    log.warning(
                        "g2b.network_error",
                        method=method,
                        path=path,
                        attempt=attempt,
                        error=str(exc),
                    )
                    if attempt >= self._max_retries:
                        raise UpstreamUnavailableError("g2b network error") from exc
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue

            log.info(
                "g2b.request",
                method=method,
                path=path,
                status=resp.status_code,
                attempt=attempt,
            )

            if resp.status_code < 400:
                return resp

            # Treat 410 specially on voucher delivery polling — it means the
            # order failed at G2B (refunded / cancelled). Caller asks for
            # terminal-failure mapping; everything else raises G2bError.
            if resp.status_code == 410 and treat_410_as == "terminal_failure":
                raise G2bTerminalFailure(_safe_body(resp))

            if resp.status_code == 401:
                # CRITICAL: a few 401s in a row get our IP permanently banned.
                # Stop retrying immediately and let the caller decide what to do
                # (typically: surface a config error and refuse to keep calling).
                raise G2bError(resp.status_code, _safe_body(resp))

            if resp.status_code == 429 or resp.status_code >= 500:
                last_status = resp.status_code
                if attempt >= self._max_retries:
                    raise UpstreamUnavailableError(
                        f"g2b retries exhausted (last HTTP {last_status})"
                    )
                await asyncio.sleep(delay)
                delay *= 2
                continue

            # Other 4xx — non-retryable.
            raise G2bError(resp.status_code, _safe_body(resp))

        raise UpstreamUnavailableError(f"g2b unreachable after {self._max_retries + 1} attempts")

    # ---------- endpoints ----------

    async def get_me(self) -> dict[str, Any]:
        resp = await self._request("GET", "/getMe")
        return resp.json()  # type: ignore[no-any-return]

    async def purchase_voucher(
        self,
        *,
        product_id: str,
        quantity: int,
        idempotency_key: str,
    ) -> VoucherPurchaseResult:
        resp = await self._request(
            "POST",
            f"/products/{product_id}/purchase",
            json={"quantity": quantity},
            idempotency_key=idempotency_key,
        )
        body = resp.json()
        raw_status = str(body.get("status") or "").upper()
        outcome: VoucherOutcome
        if raw_status == "COMPLETED":
            outcome = "completed"
        elif raw_status == "PENDING":
            outcome = "pending"
        else:
            outcome = "failed"
        return VoucherPurchaseResult(
            g2b_order_id=str(body.get("order_id")),
            status=outcome,
            delivery_items=body.get("delivery_items"),
        )

    async def poll_voucher_delivery(self, g2b_order_id: str) -> VoucherDeliveryResult:
        """Polls ``/orders/:id/delivery``.

        Maps the docstring's HTTP-code semantics to a discriminated union:
        - 200 → completed, codes attached
        - 202 → still pending
        - 410 → terminal failure (raises :class:`G2bTerminalFailure`)
        """
        resp = await self._request(
            "GET",
            f"/orders/{g2b_order_id}/delivery",
            treat_410_as="terminal_failure",
        )
        if resp.status_code == 202:
            return VoucherDeliveryResult(status="pending", delivery_items=None)
        body = resp.json()
        return VoucherDeliveryResult(
            status="completed",
            delivery_items=body.get("delivery_items"),
        )

    async def create_game_order(
        self,
        *,
        game_code: str,
        catalogue_name: str,
        player_id: str,
        server_id: str | None,
        charname: str | None,
        callback_url: str | None,
        remark: str | None,
        idempotency_key: str,
    ) -> GameOrderCreated:
        payload: dict[str, Any] = {
            "catalogue_name": catalogue_name,
            "player_id": player_id,
        }
        if server_id:
            payload["server_id"] = server_id
        if charname:
            payload["charname"] = charname
        if callback_url:
            payload["callback_url"] = callback_url
        if remark:
            payload["remark"] = remark

        resp = await self._request(
            "POST",
            f"/games/{game_code}/order",
            json=payload,
            idempotency_key=idempotency_key,
        )
        body = resp.json()
        return GameOrderCreated(
            g2b_order_id=str(body.get("order_id")),
            status=_normalise_game_status(body.get("status")),
        )

    async def get_game_order_status(self, *, g2b_order_id: str, game_code: str) -> GameOrderStatus:
        resp = await self._request(
            "POST",
            "/games/order/status",
            json={"order_id": g2b_order_id, "game": game_code},
        )
        body = resp.json()
        return GameOrderStatus(
            g2b_order_id=str(body.get("order_id")),
            status=_normalise_game_status(body.get("status")),
            message=body.get("message"),
        )

    async def games_fields(self, game_code: str) -> dict[str, Any]:
        resp = await self._request("POST", "/games/fields", json={"game": game_code})
        return resp.json()  # type: ignore[no-any-return]

    async def games_check_player(
        self,
        *,
        game_code: str,
        player_id: str,
        server_id: str | None,
        charname: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"game": game_code, "user_id": player_id}
        if server_id:
            payload["server_id"] = server_id
        if charname:
            payload["charname"] = charname
        resp = await self._request("POST", "/games/checkPlayerId", json=payload)
        return resp.json()  # type: ignore[no-any-return]

    async def fetch_products(self, *, page: int = 1, limit: int = 100) -> list[dict[str, Any]]:
        resp = await self._request("GET", f"/products?page={page}&limit={limit}")
        body = resp.json()
        items = body.get("items") or body.get("data") or body
        if isinstance(items, list):
            return [it for it in items if isinstance(it, dict)]
        return []

    async def fetch_games(self) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/games")
        body = resp.json()
        items = body.get("items") or body.get("data") or body
        if isinstance(items, list):
            return [it for it in items if isinstance(it, dict)]
        return []


def _safe_body(resp: httpx.Response) -> str:
    """Return at most 500 chars of the response body for logging / errors."""
    try:
        return resp.text[:500]
    except (UnicodeDecodeError, AttributeError):
        return "<binary>"


def _normalise_game_status(
    raw: Any,
) -> Literal["pending", "processing", "completed", "failed"]:
    s = str(raw or "").upper()
    if s == "COMPLETED":
        return "completed"
    if s in {"FAILED", "CANCELLED", "REFUNDED"}:
        return "failed"
    if s == "PROCESSING":
        return "processing"
    return "pending"


def generate_webhook_secret() -> str:
    """Helper for ops: ``python -c '...'`` style generation. Not used at runtime."""
    return secrets.token_urlsafe(32)


__all__ = [
    "G2bClient",
    "G2bError",
    "G2bTerminalFailure",
    "GameOrderCreated",
    "GameOrderStatus",
    "VoucherDeliveryResult",
    "VoucherOutcome",
    "VoucherPurchaseResult",
    "generate_webhook_secret",
]
