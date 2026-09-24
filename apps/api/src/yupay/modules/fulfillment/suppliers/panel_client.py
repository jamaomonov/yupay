"""The reseller-panel API v2 wire format, shared by more than one vendor.

NOVA (``nova-gifts.com``) and FazerCards (``api.fzr.cards``) publish the **same
API**. Measured on 2026-09-24, not assumed: all twelve ``/api/v2`` paths this
integration calls exist on both under identical names, with the same
``X-API-Key`` header, the same ``{ok, …}`` envelope, the same cursor paging
(``meta.next_cursor``), the same ``offers``-not-``items`` quirk on
``/giftcards/cards``, and the same per-category ``fields`` declaration. On 38 of
the 39 SKUs we buy from NOVA, FazerCards quotes exactly ``nova_price / 1.02``.

Whether one white-labels the other or both resell a third party is not
something we can see from outside, and it does not change what this module is
for: the wire format is one format, so it is written once.

**What is deliberately *not* here.** Anything a vendor does differently:

* NOVA's Fragment endpoints (``/api/v1/fragment/*``) — a second API on the same
  host with no ``ok`` envelope, which FazerCards does not have at all;
* the idempotency contract. Their *documentation* agrees — a reused key
  "returns the original order" — but NOVA's live API answers ``409 This
  Idempotency-Key was already used``. FazerCards' behaviour is **unverified**
  (our account has no balance to test a duplicate create with), so each
  adapter states its own contract and neither inherits an assumption.

Subclasses set :attr:`PanelClient.slug` and the two exception types, so every
log event and every error sentence names the vendor that produced it. That is
not cosmetic: the runbooks grep on ``nova.*``.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, ClassVar

import httpx

from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.base import transport_error_text

#: Their own ceiling on ``limit`` for the paged catalogue lists.
MAX_PAGE = 100

#: How many cursor pages one catalogue walk will follow before giving up. At
#: the 100-per-page ceiling that is 5,000 categories against the ~300 top-ups
#: and ~580 gift cards they publish — a guard against a cursor that never
#: terminates, not a real limit.
_MAX_PAGES = 50


class PanelError(Exception):
    """The panel refused the call (transport fine, business failure).

    Args:
        message: The most useful sentence they sent — see :func:`message_of`.
        status: HTTP status. ``200`` when the refusal came as ``ok: false``.
        code: Their machine-readable ``code``, when they sent one. It is
            optional in their schema, so no caller may require it.
        body: The raw response text, truncated. A caller sometimes has to
            re-read the payload to tell a real fault from a legitimate verdict.
    """

    def __init__(self, message: str, *, status: int = 200, code: str = "", body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body


class PanelUnavailableError(Exception):
    """The panel could not be reached at all (network error, timeout, DNS)."""


@dataclass(frozen=True)
class PanelValidation:
    """One ``POST /topups/validate-id`` answer.

    Attributes:
        valid: Whether the id exists for that game.
        player_name: The nickname, when they report one.
        region: Their region word (observed on NOVA: ``"Russia"``). Its meaning
            across our region-split brands is unproven, so only the player
            check's region guard reads it.
    """

    valid: bool
    player_name: str | None
    region: str | None


def message_of(body: dict[str, Any], status: int, *, slug: str) -> str:
    """The most useful sentence in a refusal.

    **There are two error envelopes and only one of them is documented.** The
    OpenAPI describes ``{"ok": false, "error": "…", "code": "…"}``; what a real
    409/400/502 returns is ``{"message": "This Idempotency-Key was already used
    …", "error": "Conflict", "statusCode": 409}`` — observed live on NOVA,
    2026-09-17. In that second shape ``error`` holds the *status name*, so
    reading it first turns an actionable sentence into the word "Conflict",
    which is what would land in ``task.last_error`` for a human to act on.

    So: ``message`` when there is one, then ``error``, then the status.
    """
    for key in ("message", "error"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{slug} HTTP {status}"


def order_with_debit(body: dict[str, Any]) -> dict[str, Any]:
    """Their order, with what they charged us folded in.

    A create answers ``{ok, order, <vendor>Debit}``: the order says what was
    bought and the debit's ``amountUsd`` says what it cost us, and those are
    different numbers for Steam, where a plan discount applies. A later ``GET``
    of the same order carries ``chargedUsd`` instead. One key has to answer
    "what were we charged" on both paths, or the caller needs to know which
    call it is holding — so the create's debit is written under the name the
    ``GET`` uses.

    The debit key is vendor-prefixed (``novaDebit``), so rather than guess each
    vendor's spelling this accepts **any** key ending in ``Debit``.
    """
    order = body.get("order")
    if not isinstance(order, dict):
        return {}
    debit = next(
        (v for k, v in body.items() if k.endswith("Debit") and isinstance(v, dict)),
        None,
    )
    if debit is None:
        return order
    amount = debit.get("amountUsd")
    if amount in (None, ""):
        return order
    merged = dict(order)
    merged.setdefault("chargedUsd", amount)
    return merged


class PanelClient:
    """Thin async client over the panel v2 endpoints this integration uses.

    Transport only: it speaks the wire format and raises on refusals. Order
    state interpretation lives in the fulfiller that wraps this client.
    """

    #: Vendor slug. Prefixes every log event and every generated error
    #: sentence, so an operator can tell which supplier produced a line.
    slug: ClassVar[str] = "panel"
    #: Raised on a refusal. Subclasses narrow it so ``except NovaError`` keeps
    #: catching only NOVA.
    error_cls: ClassVar[type[PanelError]] = PanelError
    #: Raised when nothing was decided upstream.
    unavailable_cls: ClassVar[type[PanelUnavailableError]] = PanelUnavailableError

    def __init__(self, *, api_key: str, base_url: str, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._log = get_logger(f"yupay.fulfillment.{self.slug}")

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
        """One call.

        Raises:
            PanelUnavailableError: Nothing was decided upstream. Subclasses
                narrow the type.
            PanelError: They answered a refusal — including an ``ok: false``
                that arrived on an HTTP 200, which is why the status code
                alone never decides whether a call worked.
        """
        try:
            async with self._session(timeout=timeout) as client:
                resp = await client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            # Network-level: nothing was decided upstream, which is a different
            # fact from a refusal and is graded differently by the caller.
            raise self.unavailable_cls(transport_error_text(exc)) from exc

        text = resp.text[:500]
        self._log.info(f"{self.slug}.request", method=method, path=path, status=resp.status_code)
        try:
            body = resp.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise self.error_cls(
                f"{self.slug} returned non-JSON", status=resp.status_code, body=text
            )
        if resp.status_code >= 400 or body.get("ok") is not True:
            raise self.error_cls(
                message_of(body, resp.status_code, slug=self.slug),
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

    async def _walk(self, path: str, *, what: str) -> list[dict[str, Any]]:
        """Every page of a cursor-paged category list.

        Args:
            path: The list endpoint.
            what: Name for the runaway-cursor warning.

        Returns:
            Every ``items`` row across the walk.
        """
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _page in range(_MAX_PAGES):
            params: dict[str, Any] = {"limit": MAX_PAGE}
            if cursor:
                params["cursor"] = cursor
            body = await self._request("GET", path, params=params)
            items += [i for i in (body.get("items") or []) if isinstance(i, dict)]
            cursor = ((body.get("meta") or {}).get("next_cursor")) or None
            if not cursor:
                break
        else:
            # The catalogue was ~306 top-up categories when this was written,
            # so the ceiling is a runaway-cursor guard rather than a real
            # limit. Say so when it trips: a silently short catalogue reads as
            # "they dropped the game we sell", and the seed that consumes this
            # would then report perfectly good SKUs as unmatched.
            self._log.warning(
                f"{self.slug}.{what}_page_limit_hit", pages=_MAX_PAGES, collected=len(items)
            )
        return items

    async def list_topups(self) -> list[dict[str, Any]]:
        """Every top-up category, walking their cursor to the end."""
        return await self._walk("/api/v2/topups", what="topups")

    async def list_giftcards(self) -> list[dict[str, Any]]:
        """Every gift-card category, walking their cursor to the end.

        The top-up catalogue's twin, paged the same way, but a **separate
        namespace**: ``roblox_global`` is a gift-card category id and means
        nothing to ``/topups``.
        """
        return await self._walk("/api/v2/giftcards", what="giftcards")

    async def get_offers(self, category_id: str) -> dict[str, Any]:
        """Offers and input fields for one top-up category."""
        return await self._request(
            "GET", "/api/v2/topups/offers", params={"category_id": category_id}
        )

    async def list_giftcard_cards(self, category_id: str) -> list[dict[str, Any]]:
        """Every denomination of one gift-card category, with its live stock.

        One call answers the whole category — nine rows for ``roblox_global`` —
        so the stock sweep caches it per category instead of asking once per
        SKU.

        The endpoint is **not** ``/giftcards/offers``; that 404s. The array is
        under ``offers``, not ``items``, which is worth saying because every
        other list on this API uses ``items``.
        """
        body = await self._request(
            "GET", "/api/v2/giftcards/cards", params={"category_id": category_id}
        )
        rows = body.get("offers")
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    # ---------- ordering ----------

    def _idem(self, idempotency_key: str) -> dict[str, str]:
        """The idempotency header, truncated to their 255-char ceiling."""
        return {"Idempotency-Key": idempotency_key[:255]}

    async def create_topup_order(
        self,
        *,
        category_id: str,
        offer_id: str,
        fields: dict[str, str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Place one top-up order and return their order object.

        The key always travels: a retry without one would be a second
        purchase. What a *reused* key does differs per vendor and is stated on
        each adapter, never assumed here.
        """
        body = await self._request(
            "POST",
            "/api/v2/topups/order",
            json={"category_id": category_id, "offer_id": offer_id, "fields": fields},
            headers=self._idem(idempotency_key),
        )
        return order_with_debit(body)

    async def create_giftcard_order(
        self,
        *,
        category_id: str,
        card_id: str,
        quantity: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Buy gift-card codes. Their gift-card endpoint, not the top-ups one.

        A gift card has no player to credit, so this sends no ``fields`` at all
        — which is exactly why it cannot ride on :meth:`create_topup_order`,
        whose body requires them.

        Delivery is **asynchronous even when it is fast**. Measured on NOVA's
        first live order (2026-09-21, ``roblox_global`` / ``50_robux``): the
        create answered ``status: "created"`` with ``cards: []`` and the money
        already debited, and ``GET /api/v2/orders/{id}`` answered ``completed``
        with one code about a second later. So a caller must poll rather than
        read codes off the create — the codes are on the ORDER, never in the
        create response.

        Args:
            category_id: ``category_id`` from ``GET /api/v2/giftcards``.
            card_id: ``card_id`` from ``GET /api/v2/giftcards/cards`` — the
                denomination within that category.
            quantity: How many codes. Their schema allows 1-100 and stock caps
                it lower; the caller is responsible for not asking for more
                than ``max_order_quantity``.
            idempotency_key: Always sent, per :meth:`create_topup_order`.
        """
        body = await self._request(
            "POST",
            "/api/v2/giftcards/order",
            json={"category_id": category_id, "card_id": card_id, "quantity": quantity},
            headers=self._idem(idempotency_key),
        )
        return order_with_debit(body)

    async def create_steam_order(
        self, *, steam_login: str, amount_usd: Decimal, idempotency_key: str
    ) -> dict[str, Any]:
        """Top up a Steam wallet. Their Steam endpoint, not the games one.

        Different in three ways that all matter: it takes a login and an amount
        rather than a category and an offer, it answers ``201``, and what it
        charges us is **not** the amount — a plan discount applies, which is
        why the debit reported beside the order is folded in.

        Args:
            steam_login: The customer's login. Never logged.
            amount_usd: Face value in dollars — what the customer receives.
                Sent with at most two decimals, which their schema requires;
                rounding is half-up so a fraction of a cent is never taken off
                what was bought.
            idempotency_key: Always sent, per :meth:`create_topup_order`.
        """
        amount = amount_usd.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        body = await self._request(
            "POST",
            "/api/v2/steam-topup/order",
            json={"steamLogin": steam_login, "currency": "USD", "amount": f"{amount}"},
            headers=self._idem(idempotency_key),
        )
        return order_with_debit(body)

    # ---------- order state ----------

    async def list_orders(self, *, limit: int = 50, page: int = 1) -> list[dict[str, Any]]:
        """``GET /api/v2/orders`` — our recent orders, newest first.

        The only way to find an order whose create response we never saw.
        There are no filters: the endpoint takes ``page`` and ``limit`` and
        nothing else, so the match happens on our side.

        Returns ``[]`` rather than raising when the envelope is not the shape
        we expect — a probe that cannot read the list has not found anything,
        which is the same answer as an empty list to every caller here.
        """
        body = await self._request("GET", "/api/v2/orders", params={"limit": limit, "page": page})
        items = body.get("items")
        return [row for row in items if isinstance(row, dict)] if isinstance(items, list) else []

    async def get_order(self, order_id: str) -> dict[str, Any]:
        """One order by their public id."""
        body = await self._request("GET", f"/api/v2/orders/{order_id}")
        order = body.get("order")
        return order if isinstance(order, dict) else {}

    # ---------- advisory checks ----------

    async def validate_id(
        self, *, category_id: str, fields: dict[str, str], timeout: float | None = None
    ) -> PanelValidation:
        """Check a player id. A ``422`` ("could not be confirmed") raises.

        Note the namespaces: ``mobile_legends`` validates a player;
        ``mobile_legends_global`` and ``mobile_legends_ru`` sell to one.
        Nothing in the API links them, and passing one where the other belongs
        is a 404 at best.
        """
        body = await self._request(
            "POST",
            "/api/v2/topups/validate-id",
            json={"category_id": category_id, "fields": fields},
            timeout=timeout,
        )
        name = body.get("player_name")
        region = body.get("region")
        return PanelValidation(
            valid=bool(body.get("valid")),
            player_name=str(name) if name else None,
            region=str(region) if region else None,
        )

    async def check_steam_login(self, steam_login: str, *, timeout: float | None = None) -> bool:
        """Whether they can top up that Steam account.

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
    "PanelClient",
    "PanelError",
    "PanelUnavailableError",
    "PanelValidation",
    "message_of",
    "order_with_debit",
]
