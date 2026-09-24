"""HTTP client for NOVA's public API v2 (nova-gifts.com).

Transport only: it speaks the wire format and raises on refusals. Order state
interpretation lives in the fulfiller that wraps this client.

**Most of the wire format is not here.** It lives in ``panel_client``, because
NOVA and FazerCards publish the same API — all twelve ``/api/v2`` paths this
integration calls, byte for byte the same names and envelopes (measured
2026-09-24). What stays in this file is the part that is NOVA's alone.

Four things about this API drive the shape, all verified against the live
service on 2026-09-17 — the last two by placing a real order:

* Auth is an ``X-API-Key`` header (``ng_…``).
* **A success carries ``ok``, and a refusal may not.** ``ok: false`` can arrive
  on an HTTP 200, so the status code alone never decides whether a call worked;
  and their real 4xx/5xx bodies use a second, undocumented envelope where the
  useful sentence is in ``message``. Both live in ``panel_client``.
* **A reused ``Idempotency-Key`` is refused, not replayed.** Their endpoint
  description says a repeat "returns the original order"; the live API answers
  ``409 This Idempotency-Key was already used for a purchase``. The parameter
  description, which says the opposite of the endpoint description, is the one
  that is true — so a create is never safely retried under the same key, and
  the header is genuinely required (without it: ``400``). **This is NOVA's
  contract, not the platform's** — FazerCards is unverified on this point and
  states its own.
* **Validate ids and top-up ids are different namespaces.** ``mobile_legends``
  validates a player; ``mobile_legends_global`` and ``mobile_legends_ru`` sell
  to one. Nothing in the API links them, and passing one where the other
  belongs is a 404 at best.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from yupay.core.logging import get_logger
from yupay.modules.fulfillment.suppliers.base import transport_error_text
from yupay.modules.fulfillment.suppliers.panel_client import (
    MAX_PAGE,
    PanelClient,
    PanelError,
    PanelUnavailableError,
    PanelValidation,
    message_of,
)

log = get_logger("yupay.fulfillment.nova")


class NovaError(PanelError):
    """NOVA refused the call (transport fine, business failure)."""


class NovaUnavailableError(PanelUnavailableError):
    """NOVA could not be reached at all (network error, timeout, DNS)."""


#: One ``POST /topups/validate-id`` answer. The platform shape; the alias is
#: kept because ``player_check_nova`` and its tests read this name.
NovaValidation = PanelValidation


class NovaClient(PanelClient):
    """Thin async client over the endpoints this integration uses.

    Everything in ``panel_client`` plus NOVA's Fragment API below.
    """

    slug: ClassVar[str] = "nova"
    error_cls: ClassVar[type[PanelError]] = NovaError
    unavailable_cls: ClassVar[type[PanelUnavailableError]] = NovaUnavailableError

    # ---------- Fragment (Telegram) ----------
    #
    # A second API on the same host and the same key, and it agrees with the
    # v2 one on almost nothing. Verified against their published spec and by
    # calling the quote endpoints on 2026-09-20:
    #
    # * **No ``ok`` envelope.** A Fragment 200 is the payload itself, so
    #   ``PanelClient._request`` — which refuses anything without ``ok: true``
    #   — raises on every successful call. Hence the separate path below.
    # * **A reused ``Idempotency-Key`` returns the existing order**, the exact
    #   opposite of the v2 endpoints, where a repeat is refused with ``409``.
    #   Their key pattern is ``^[A-Za-z0-9._:-]+$``, max 128.
    # * A quote is **not** a validation. ``premium/quote`` answered
    #   ``customer_amount_usd`` for a username that does not exist and simply
    #   echoed it back as ``recipient`` — it is a calculator, nothing more.
    #   Anything that needs to know a username is real must ask elsewhere.
    #
    # FazerCards has no equivalent: its Telegram products are ordinary v2
    # endpoints (``/api/v2/telegram/stars/buy``). Another reason this stays
    # out of the shared client.

    async def _fragment_request(
        self,
        method: str,
        path: str,
        *,
        timeout: float | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """One Fragment call. Same errors as ``_request``, no envelope."""
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
            # Fragment reports a refusal in ``detail``; ``message_of`` already
            # reads that key, and falls back to the v2 shapes for a body that
            # turns out to use them after all.
            raise NovaError(
                message_of(body, resp.status_code, slug="nova"),
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
