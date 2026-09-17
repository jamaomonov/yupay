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

#: How many cursor pages one catalogue walk will follow before giving up. At
#: their 100-per-page ceiling that is 5,000 categories against the 306 they
#: publish — a guard against a cursor that never terminates, not a limit.
_MAX_PAGES = 50


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
