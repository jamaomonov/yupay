"""HTTP client for the csmarket public purchase API (ADR-0098).

Transport only: it speaks the wire format of ``api.csmarket.uz/api/v1/public`` and raises on
refusals; what a refusal means for an order lives in the skins fulfiller.

Facts about this API that shape the code:

* One bearer token (``csm_…``), no request signing.
* Money is a USD string with three decimals. This layer converts it to integer milli-USD
  units (``1000 = $1``) — the unit ``skins`` already prices in, so the catalogue and the
  pricing rules need no second scale.
* Errors are RFC 7807 with a machine ``code``: :class:`CsmarketError` carries it, and
  ``extra`` keeps the rest of the body (``order`` on ``duplicate_client_order_id``,
  ``price_usd`` on ``price_above_max``).
* The feed's first page is limited to one call a minute per key, revalidation included;
  a 429 carries ``Retry-After``.
* The edge refuses ``Python-urllib``'s user agent; httpx's passes, and we send our own.

The token is a credential: it is never logged, and neither is a trade link (its ``token``
lets anyone send that account offers).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import httpx

from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.base import transport_error_text

log = get_logger("yupay.fulfillment.csmarket")

USER_AGENT = "yupay-api/1.0 (+https://yupay.uz)"
_UNITS_PER_USD = Decimal(1000)

CsmOrderStatus = Literal["buying", "trade_sent", "delivered", "refunded", "unknown"]
TradelinkVerdict = Literal["ok", "bad", "unavailable"]


class CsmarketError(Exception):
    """csmarket answered with an error (transport fine, business refusal).

    Args:
        message: ``detail`` of the problem body, or the raw text.
        status: HTTP status.
        code: the problem's machine ``code`` (``offer_gone``, ``insufficient_balance``…).
        extra: every other field of the problem body.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int,
        code: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.extra = extra or {}


class CsmarketRateLimitedError(CsmarketError):
    """HTTP 429. ``retry_after`` is csmarket's own hint in seconds when it gave one."""

    def __init__(self, message: str, *, retry_after: int | None, code: str = "") -> None:
        super().__init__(message, status=429, code=code or "rate_limited")
        self.retry_after = retry_after


class CsmarketUnavailableError(Exception):
    """csmarket could not be reached, or answered 5xx: the call may or may not have landed."""


def usd_to_units(raw: object) -> int:
    """``"12.345"`` → ``12345``. Raises ``ValueError`` on anything that is not a price."""
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a USD amount: {raw!r}") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"not a USD amount: {raw!r}")
    return int((value * _UNITS_PER_USD).to_integral_value())


def units_to_usd(units: int) -> str:
    """``12345`` → ``"12.345"`` — the three-decimal string the API expects."""
    return f"{Decimal(units) / _UNITS_PER_USD:.3f}"


def _dt(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class FeedItem:
    """One catalogue item on the key's tariff. ``price_units`` is the cheapest offer."""

    item_id: str
    slug: str
    market_hash_name: str
    exterior: str | None
    price_units: int
    stock: int
    retail_price_units: int | None
    updated_at: datetime | None


@dataclass(frozen=True)
class FeedPage:
    """One page of the feed; ``next_cursor`` is ``None`` on the last page."""

    items: list[FeedItem]
    next_cursor: str | None
    etag: str | None


@dataclass(frozen=True)
class Offer:
    """One live offer of an item, cheapest first in a list."""

    offer_id: str
    price_units: int
    float_value: float | None
    paint_seed: int | None
    stickers: list[dict[str, Any]]
    delivery: str | None
    retail_price_units: int | None = None


@dataclass(frozen=True)
class CsmTrade:
    offer_sent_at: datetime | None
    accepted_at: datetime | None
    release_at: datetime | None
    steam_offer_id: str | None
    seller_name: str | None


@dataclass(frozen=True)
class CsmOrder:
    """An API order as csmarket reports it."""

    order_id: str
    client_order_id: str
    status: CsmOrderStatus
    price_units: int
    item_id: str | None
    market_hash_name: str | None
    trade: CsmTrade | None
    refund_units: int | None
    refund_reason: str | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class CsmMe:
    balance_units: int
    usd_wallet_enabled: bool
    pricing_profile: str
    limits: dict[str, int]


_STATUSES: frozenset[str] = frozenset({"buying", "trade_sent", "delivered", "refunded"})


def _feed_item(raw: dict[str, Any]) -> FeedItem | None:
    try:
        retail = raw.get("retail_price_usd")
        stock = raw.get("stock")
        return FeedItem(
            item_id=str(raw["item_id"]),
            slug=str(raw["slug"]),
            market_hash_name=str(raw["market_hash_name"]),
            exterior=str(raw["exterior"]) if raw.get("exterior") else None,
            price_units=usd_to_units(raw["price_usd"]),
            stock=int(stock) if isinstance(stock, int) and not isinstance(stock, bool) else 0,
            retail_price_units=usd_to_units(retail) if retail is not None else None,
            updated_at=_dt(raw.get("updated_at")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _sticker(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        return None
    image, slot, wear = raw.get("image"), raw.get("slot"), raw.get("wear")
    return {
        "name": name,
        "image": image if isinstance(image, str) else None,
        "slot": slot if isinstance(slot, int) and not isinstance(slot, bool) else None,
        "wear": float(wear)
        if isinstance(wear, int | float) and not isinstance(wear, bool)
        else None,
    }


def _offer(raw: dict[str, Any]) -> Offer | None:
    try:
        offer_id = raw["offer_id"]
        if not isinstance(offer_id, str) or not offer_id:
            return None
        flt, seed, retail = raw.get("float"), raw.get("paint_seed"), raw.get("retail_price_usd")
        return Offer(
            offer_id=offer_id,
            price_units=usd_to_units(raw["price_usd"]),
            float_value=float(flt)
            if isinstance(flt, int | float) and not isinstance(flt, bool)
            else None,
            paint_seed=seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
            stickers=[
                s for raw_s in raw.get("stickers") or [] if (s := _sticker(raw_s)) is not None
            ],
            delivery=raw.get("delivery") if isinstance(raw.get("delivery"), str) else None,
            retail_price_units=usd_to_units(retail) if retail is not None else None,
        )
    except (KeyError, TypeError, ValueError):
        return None


def parse_order(raw: dict[str, Any]) -> CsmOrder:
    """An order object from ``GET /orders/{id}``, ``POST /orders`` or a webhook payload.

    Raises:
        CsmarketError: the body is not an order (status 200, code ``bad_shape``).
    """
    try:
        status_raw = str(raw["status"])
        status: CsmOrderStatus = status_raw if status_raw in _STATUSES else "unknown"  # type: ignore[assignment] # narrowed by the set
        trade_raw = raw.get("trade")
        trade = (
            CsmTrade(
                offer_sent_at=_dt(trade_raw.get("offer_sent_at")),
                accepted_at=_dt(trade_raw.get("accepted_at")),
                release_at=_dt(trade_raw.get("release_at")),
                steam_offer_id=str(trade_raw["steam_offer_id"])
                if trade_raw.get("steam_offer_id")
                else None,
                seller_name=str(trade_raw["seller_name"]) if trade_raw.get("seller_name") else None,
            )
            if isinstance(trade_raw, dict)
            else None
        )
        refund = raw.get("refund")
        item_raw = raw.get("item")
        item: dict[str, Any] = item_raw if isinstance(item_raw, dict) else {}
        return CsmOrder(
            order_id=str(raw["order_id"]),
            client_order_id=str(raw.get("client_order_id") or ""),
            status=status,
            price_units=usd_to_units(raw["price_usd"]),
            item_id=str(item["item_id"]) if item.get("item_id") else None,
            market_hash_name=str(item["market_hash_name"])
            if item.get("market_hash_name")
            else None,
            trade=trade,
            refund_units=usd_to_units(refund["amount_usd"])
            if isinstance(refund, dict) and refund.get("amount_usd") is not None
            else None,
            refund_reason=str(refund["reason"])
            if isinstance(refund, dict) and refund.get("reason")
            else None,
            raw=raw,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CsmarketError(
            "csmarket order has an unexpected shape", status=200, code="bad_shape"
        ) from exc


class CsmarketClient:
    """Async client for the csmarket public API.

    Pass ``client`` to inject an ``httpx.AsyncClient`` in tests; ``None`` opens a transient
    one per call.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client

    @property
    def configured(self) -> bool:
        """Whether a key is set at all."""
        return bool(self._api_key)

    @contextlib.asynccontextmanager
    async def _session(self, timeout: float | None) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(timeout=timeout or self._timeout) as client:
            yield client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        allow_not_modified: bool = False,
    ) -> httpx.Response:
        """Send one call; raise on transport failure, 5xx, 429 and any other error status.

        Raises:
            CsmarketUnavailableError: network failure or 5xx.
            CsmarketRateLimitedError: 429.
            CsmarketError: any other status ≥ 400.
        """
        send_headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            **(headers or {}),
        }
        try:
            async with self._session(timeout) as client:
                resp = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    params=params,
                    json=json,
                    headers=send_headers,
                    timeout=timeout or self._timeout,
                )
        except httpx.HTTPError as exc:
            log.warning(
                "csmarket.network_error", method=method, path=path, error=transport_error_text(exc)
            )
            raise CsmarketUnavailableError(transport_error_text(exc)) from exc

        log.info("csmarket.request", method=method, path=path, status=resp.status_code)
        if resp.status_code == 304 and allow_not_modified:
            return resp
        if resp.status_code >= 500:
            raise CsmarketUnavailableError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        if resp.status_code >= 400:
            problem: dict[str, Any] = {}
            with contextlib.suppress(ValueError):
                body = resp.json()
                if isinstance(body, dict):
                    problem = body
            code = str(problem.get("code") or "")
            detail = str(problem.get("detail") or problem.get("title") or resp.text[:200])
            if resp.status_code == 429:
                retry = resp.headers.get("Retry-After")
                raise CsmarketRateLimitedError(
                    detail, retry_after=int(retry) if retry and retry.isdigit() else None, code=code
                )
            extra = {
                k: v
                for k, v in problem.items()
                if k not in {"type", "title", "status", "detail", "code"}
            }
            raise CsmarketError(detail, status=resp.status_code, code=code, extra=extra)
        return resp

    async def me(self) -> CsmMe:
        """``GET /me`` — the USD balance, the key's tariff and its limits."""
        body = (await self._request("GET", "/me")).json()
        try:
            key = body.get("key") or {}
            return CsmMe(
                balance_units=usd_to_units(body["balance_usd"]),
                usd_wallet_enabled=bool(body.get("usd_wallet_enabled")),
                pricing_profile=str(key.get("pricing_profile") or ""),
                limits={
                    k: int(v) for k, v in (body.get("limits") or {}).items() if isinstance(v, int)
                },
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CsmarketError(
                "csmarket /me has an unexpected shape", status=200, code="bad_shape"
            ) from exc

    async def catalog_page(
        self, *, cursor: str | None = None, etag: str | None = None
    ) -> FeedPage | None:
        """One page of ``GET /catalog``; ``None`` when ``etag`` still matches (304).

        Items that do not parse are skipped, not fatal: one odd row must not stop a sweep.
        """
        resp = await self._request(
            "GET",
            "/catalog",
            params={"cursor": cursor} if cursor else None,
            headers={"If-None-Match": etag} if etag else None,
            allow_not_modified=True,
        )
        if resp.status_code == 304:
            return None
        body = resp.json()
        rows = body.get("items") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise CsmarketError(
                "csmarket feed has an unexpected shape", status=200, code="bad_shape"
            )
        items = [
            item for raw in rows if isinstance(raw, dict) and (item := _feed_item(raw)) is not None
        ]
        nxt = body.get("next_cursor")
        return FeedPage(
            items=items, next_cursor=str(nxt) if nxt else None, etag=resp.headers.get("ETag")
        )

    async def iter_catalog(self) -> AsyncIterator[FeedItem]:
        """Every item of one snapshot, page by page."""
        cursor: str | None = None
        while True:
            page = await self.catalog_page(cursor=cursor)
            if page is None:  # pragma: no cover - no etag sent, so never 304
                return
            for item in page.items:
                yield item
            if page.next_cursor is None:
                return
            cursor = page.next_cursor

    async def offers(self, item_id: str, *, timeout: float | None = None) -> list[Offer]:
        """``GET /catalog/{item_id}/offers`` — live offers, cheapest first.

        Raises:
            CsmarketError: ``item_not_found`` (404) among others.
        """
        body = (await self._request("GET", f"/catalog/{item_id}/offers", timeout=timeout)).json()
        if not isinstance(body, list):
            raise CsmarketError(
                "csmarket offers have an unexpected shape", status=200, code="bad_shape"
            )
        return [o for raw in body if isinstance(raw, dict) and (o := _offer(raw)) is not None]

    async def create_order(
        self,
        *,
        item_id: str,
        offer_id: str | None,
        max_price_units: int,
        trade_link: str,
        client_order_id: str,
    ) -> tuple[CsmOrder, bool]:
        """``POST /orders``. Returns ``(order, created)``.

        A repeat of ``client_order_id`` answers 409 ``duplicate_client_order_id`` with the
        existing order: that is returned with ``created=False`` instead of raising, so a lost
        answer is settled by asking again.

        Raises:
            CsmarketError: ``insufficient_balance`` (402), ``offer_gone`` /
                ``price_above_max`` / ``buying_disabled`` (409), ``trade_link_invalid`` (422)…
            CsmarketUnavailableError: the call may have landed — ask again with the same id.
        """
        payload: dict[str, Any] = {
            "item_id": item_id,
            "max_price_usd": units_to_usd(max_price_units),
            "trade_link": trade_link,
            "client_order_id": client_order_id,
        }
        if offer_id:
            payload["offer_id"] = offer_id
        try:
            resp = await self._request("POST", "/orders", json=payload)
        except CsmarketError as exc:
            if exc.code == "duplicate_client_order_id" and isinstance(exc.extra.get("order"), dict):
                return parse_order(exc.extra["order"]), False
            raise
        return parse_order(resp.json()), True

    async def order(self, order_id: str) -> CsmOrder:
        """``GET /orders/{order_id}``.

        Raises:
            CsmarketError: ``order_not_found`` (404).
        """
        return parse_order((await self._request("GET", f"/orders/{order_id}")).json())

    async def check_tradelink(
        self, trade_link: str, *, timeout: float | None = None
    ) -> tuple[TradelinkVerdict, str | None]:
        """``POST /tradelink/check`` → ``(verdict, reason)``. Advisory: never blocks on its own."""
        body = (
            await self._request(
                "POST", "/tradelink/check", json={"trade_link": trade_link}, timeout=timeout
            )
        ).json()
        verdict = body.get("verdict") if isinstance(body, dict) else None
        if verdict not in ("ok", "bad", "unavailable"):
            raise CsmarketError(
                "csmarket tradelink check has an unexpected shape", status=200, code="bad_shape"
            )
        reason = body.get("reason")
        return verdict, str(reason) if reason else None


__all__ = [
    "USER_AGENT",
    "CsmMe",
    "CsmOrder",
    "CsmOrderStatus",
    "CsmTrade",
    "CsmarketClient",
    "CsmarketError",
    "CsmarketRateLimitedError",
    "CsmarketUnavailableError",
    "FeedItem",
    "FeedPage",
    "Offer",
    "TradelinkVerdict",
    "parse_order",
    "units_to_usd",
    "usd_to_units",
]
