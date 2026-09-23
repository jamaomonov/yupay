"""HTTP client for NOVA's public API v2 (nova-gifts.com).

Transport only: it speaks the wire format and raises on refusals. Order state
interpretation lives in the fulfiller that wraps this client.

Four things about this API drive the shape below, all verified against the
live service on 2026-09-17 — the last two by placing a real order:

* Auth is an ``X-API-Key`` header (``ng_…``).
* **A success carries ``ok``, and a refusal may not.** ``ok: false`` can arrive
  on an HTTP 200, so the status code alone never decides whether a call worked;
  and their real 4xx/5xx bodies use a second, undocumented envelope where the
  useful sentence is in ``message`` (see :func:`_message_of`).
* **A reused ``Idempotency-Key`` is refused, not replayed.** Their endpoint
  description says a repeat "returns the original order"; the live API answers
  ``409 This Idempotency-Key was already used for a purchase``. The parameter
  description, which says the opposite of the endpoint description, is the one
  that is true — so a create is never safely retried under the same key, and
  the header is genuinely required (without it: ``400``).
* **Validate ids and top-up ids are different namespaces.** ``mobile_legends``
  validates a player; ``mobile_legends_global`` and ``mobile_legends_ru`` sell
  to one. Nothing in the API links them, and passing one where the other
  belongs is a 404 at best.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx

from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.base import transport_error_text

log = get_logger("yupay.fulfillment.nova")

#: Their own ceiling on ``limit``.
MAX_PAGE = 100

#: How many cursor pages one catalogue walk will follow before giving up. At
#: their 100-per-page ceiling that is 5,000 categories against the 306 they
#: publish — a guard against a cursor that never terminates, not a limit.
_MAX_PAGES = 50


class NovaError(Exception):
    """NOVA refused the call (transport fine, business failure).

    Args:
        message: The most useful sentence they sent — see :func:`_message_of`.
        status: HTTP status. ``200`` when the refusal came as ``ok: false``.
        code: Their machine-readable ``code``, when they sent one. It is
            optional in their schema, so no caller may require it.
        body: The raw response text, truncated. Kept for the same reason the
            G2B and G-Engine clients keep it: a caller sometimes has to re-read
            the payload to tell a real fault from a legitimate verdict.
    """

    def __init__(self, message: str, *, status: int = 200, code: str = "", body: str = "") -> None:
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


def _message_of(body: dict[str, Any], status: int) -> str:
    """The most useful sentence in a refusal.

    **They have two error envelopes and only one of them is documented.** Their
    OpenAPI describes `{"ok": false, "error": "…", "code": "…"}`; what a real
    409/400/502 returns is `{"message": "This Idempotency-Key was already used
    …", "error": "Conflict", "statusCode": 409}` — observed live on
    2026-09-17. In that second shape `error` holds the *status name*, so
    reading it first turns an actionable sentence into the word "Conflict",
    which is what lands in `task.last_error` for a human to act on.

    So: `message` when there is one, then `error`, then the status.
    """
    for key in ("message", "error"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"nova HTTP {status}"


def _order_with_debit(body: dict[str, Any]) -> dict[str, Any]:
    """Their order, with what they charged us folded in.

    A create answers ``{ok, order, novaDebit}``: the order says what was bought
    and ``novaDebit.amountUsd`` says what it cost us, and those are different
    numbers for Steam, where a plan discount applies. A later ``GET`` of the
    same order carries ``chargedUsd`` instead. One key has to answer "what were
    we charged" on both paths or the caller needs to know which call it is
    holding — so the create's debit is written under the name the ``GET`` uses.
    """
    order = body.get("order")
    if not isinstance(order, dict):
        return {}
    debit = body.get("novaDebit")
    amount = debit.get("amountUsd") if isinstance(debit, dict) else None
    return {**order, "chargedUsd": amount} if amount is not None else dict(order)


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
            raise NovaUnavailableError(transport_error_text(exc)) from exc

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
                _message_of(body, resp.status_code),
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
        for _page in range(_MAX_PAGES):
            params: dict[str, Any] = {"limit": MAX_PAGE}
            if cursor:
                params["cursor"] = cursor
            body = await self._request("GET", "/api/v2/topups", params=params)
            items += [i for i in (body.get("items") or []) if isinstance(i, dict)]
            cursor = ((body.get("meta") or {}).get("next_cursor")) or None
            if not cursor:
                break
        else:
            # Their catalogue was 306 categories when this was written, so the
            # ceiling is a runaway-cursor guard rather than a real limit. Say so
            # when it trips: a silently short catalogue reads as "they dropped
            # the game we sell", and the seed that consumes this would then
            # report perfectly good SKUs as unmatched.
            log.warning("nova.topups_page_limit_hit", pages=_MAX_PAGES, collected=len(items))
        return items

    async def list_giftcards(self) -> list[dict[str, Any]]:
        """Every gift-card category, walking their cursor to the end.

        ``GET /api/v2/giftcards`` — the top-up catalogue's twin, and paged the
        same way, but a separate namespace: ``roblox_global`` is a gift-card
        category id and means nothing to ``/topups``. 576 categories the first
        time this was walked, against 306 top-ups.
        """
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _page in range(_MAX_PAGES):
            params: dict[str, Any] = {"limit": MAX_PAGE}
            if cursor:
                params["cursor"] = cursor
            body = await self._request("GET", "/api/v2/giftcards", params=params)
            items += [i for i in (body.get("items") or []) if isinstance(i, dict)]
            cursor = ((body.get("meta") or {}).get("next_cursor")) or None
            if not cursor:
                break
        else:
            # Same guard, same reason as ``list_topups``: a silently short
            # catalogue reads as a supplier dropping what we sell.
            log.warning("nova.giftcards_page_limit_hit", pages=_MAX_PAGES, collected=len(items))
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

        Returned through :func:`_order_with_debit` like :meth:`create_steam_order`
        — for a game order the debit equals the price, so folding it in changes
        nothing here, but one shape answers "what were we charged" on both paths.
        """
        body = await self._request(
            "POST",
            "/api/v2/topups/order",
            json={"category_id": category_id, "offer_id": offer_id, "fields": fields},
            headers={"Idempotency-Key": idempotency_key[:255]},
        )
        return _order_with_debit(body)

    async def create_steam_order(
        self, *, steam_login: str, amount_usd: Decimal, idempotency_key: str
    ) -> dict[str, Any]:
        """Top up a Steam wallet. Their Steam endpoint, not the games one.

        Different in three ways that all matter: it takes a login and an amount
        rather than a category and an offer, it answers ``201``, and what it
        charges us is **not** the amount — their plan discount applies, which is
        why the debit they report beside the order is folded in below.

        Args:
            steam_login: The customer's login. Never logged.
            amount_usd: Face value in dollars — what the customer receives. Sent
                with at most two decimals, which their schema requires; rounding
                is half-up so a fraction of a cent is never taken off what was
                bought.
            idempotency_key: Required, as on every purchase of theirs. A reused
                key is refused with a ``409``, never replayed.
        """
        amount = amount_usd.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        body = await self._request(
            "POST",
            "/api/v2/steam-topup/order",
            json={"steamLogin": steam_login, "currency": "USD", "amount": f"{amount}"},
            headers={"Idempotency-Key": idempotency_key[:255]},
        )
        return _order_with_debit(body)

    async def list_giftcard_cards(self, category_id: str) -> list[dict[str, Any]]:
        """Every denomination of one gift-card category, with its live stock.

        ``GET /api/v2/giftcards/cards?category_id=…``. One call answers the
        whole category — nine rows for ``roblox_global`` — so the stock sweep
        caches it per category instead of asking once per SKU, the same shape
        G-Engine's denominations take.

        The endpoint is **not** ``/giftcards/offers``; that 404s. The array is
        under ``offers``, not ``items``, which is worth saying because every
        other list on this API uses ``items``.
        """
        body = await self._request(
            "GET", "/api/v2/giftcards/cards", params={"category_id": category_id}
        )
        rows = body.get("offers")
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

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
        — which is exactly why it could not ride on :meth:`create_topup_order`,
        whose body requires them.

        Delivery is **asynchronous even when it is fast**. Measured on the
        first live order (2026-09-21, `roblox_global` / `50_robux`): the create
        answered ``status: "created"`` with ``cards: []`` and the money already
        debited, and ``GET /api/v2/orders/{id}`` answered ``completed`` with one
        code about a second later. So a caller must poll rather than read codes
        off the create — the codes are on the ORDER, never in the create
        response.

        Args:
            category_id: ``category_id`` from ``GET /api/v2/giftcards``.
            card_id: ``card_id`` from ``GET /api/v2/giftcards/cards`` — the
                denomination within that category.
            quantity: How many codes. Their schema allows 1-100 and stock caps
                it lower; the caller is responsible for not asking for more
                than ``max_order_quantity``.
            idempotency_key: Required, as on every purchase of theirs. A reused
                key is refused with a ``409``, never replayed.
        """
        body = await self._request(
            "POST",
            "/api/v2/giftcards/order",
            json={"category_id": category_id, "card_id": card_id, "quantity": quantity},
            headers={"Idempotency-Key": idempotency_key[:255]},
        )
        return _order_with_debit(body)

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

    # ---------- Fragment (Telegram) ----------
    #
    # A second API on the same host and the same key, and it agrees with the
    # v2 one on almost nothing. Verified against their published spec and by
    # calling the quote endpoints on 2026-09-20:
    #
    # * **No ``ok`` envelope.** A Fragment 200 is the payload itself, so
    #   :meth:`_request` — which refuses anything without ``ok: true`` —
    #   raises on every successful call. Hence the separate path below.
    # * **A reused ``Idempotency-Key`` returns the existing order**, the exact
    #   opposite of the v2 endpoints, where a repeat is refused with ``409``.
    #   Their key pattern is ``^[A-Za-z0-9._:-]+$``, max 128.
    # * A quote is **not** a validation. ``premium/quote`` answered
    #   ``customer_amount_usd`` for a username that does not exist and simply
    #   echoed it back as ``recipient`` — it is a calculator, nothing more.
    #   Anything that needs to know a username is real must ask elsewhere.

    async def _fragment_request(
        self,
        method: str,
        path: str,
        *,
        timeout: float | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """One Fragment call. Same errors as :meth:`_request`, no envelope."""
        try:
            async with self._session(timeout=timeout) as client:
                resp = await client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise NovaUnavailableError(transport_error_text(exc)) from exc

        text = resp.text[:500]
        log.info("nova.fragment_request", method=method, path=path, status=resp.status_code)
        try:
            body = resp.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise NovaError("nova fragment returned non-JSON", status=resp.status_code, body=text)
        if resp.status_code >= 400:
            # Fragment reports a refusal in ``detail``; ``_message_of`` already
            # reads that key, and falls back to the v2 shapes for a body that
            # turns out to use them after all.
            raise NovaError(
                _message_of(body, resp.status_code),
                status=resp.status_code,
                code=str(body.get("code") or ""),
                body=text,
            )
        return body

    async def fragment_stars_price(self) -> dict[str, Any]:
        """Price of one Star, in USD. One number for the whole catalogue.

        Stars are linear: 50 quoted at $0.761250 and 1000 at $15.225000
        against a per-star $0.015225. So a cost basis for every Stars pack
        costs this one call rather than a quote each.
        """
        return await self._fragment_request("GET", "/fragment-api/api/v1/fragment/stars/price")

    async def fragment_stars_quote(self, *, username: str, stars_amount: int) -> dict[str, Any]:
        """What this many Stars would cost us. Does not validate ``username``."""
        return await self._fragment_request(
            "POST",
            "/fragment-api/api/v1/fragment/stars/quote",
            json={"username": username, "stars_amount": int(stars_amount)},
        )

    async def fragment_premium_quote(self, *, username: str, months: int) -> dict[str, Any]:
        """What this Premium gift would cost us. Does not validate ``username``."""
        return await self._fragment_request(
            "POST",
            "/fragment-api/api/v1/fragment/premium/quote",
            json={"username": username, "months": int(months)},
        )

    async def create_fragment_stars_order(
        self, *, username: str, stars_amount: int, idempotency_key: str
    ) -> dict[str, Any]:
        """Buy Stars for a Telegram account.

        Args:
            username: The recipient. Never logged.
            stars_amount: Whole Stars. Their free-amount shape — no pack ids.
            idempotency_key: Truncated to their 128-char ceiling. Unlike the
                v2 endpoints, a repeat returns the original order.
        """
        return await self._fragment_request(
            "POST",
            "/fragment-api/api/v1/fragment/stars",
            json={"username": username, "stars_amount": int(stars_amount)},
            headers={"Idempotency-Key": idempotency_key[:128]},
        )

    async def create_fragment_premium_order(
        self, *, username: str, months: int, idempotency_key: str
    ) -> dict[str, Any]:
        """Gift Telegram Premium. See :meth:`create_fragment_stars_order`."""
        return await self._fragment_request(
            "POST",
            "/fragment-api/api/v1/fragment/premium",
            json={"username": username, "months": int(months)},
            headers={"Idempotency-Key": idempotency_key[:128]},
        )

    async def get_fragment_order(self, order_id: str) -> dict[str, Any]:
        """One Fragment order by their id — a different namespace from
        ``/api/v2/orders/{id}``, which does not know these."""
        return await self._fragment_request(
            "GET", f"/fragment-api/api/v1/fragment/orders/{order_id}"
        )


__all__ = [
    "MAX_PAGE",
    "NovaClient",
    "NovaError",
    "NovaUnavailableError",
    "NovaValidation",
]
