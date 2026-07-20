"""HTTP client for Waxpeer's Steam wallet top-up API.

Transport only: it speaks the wire format and raises on refusals. Status
interpretation, gross-up and reconciliation live in the fulfiller that wraps
this client (a later task) — not here.

Two things about this API drive the shape below:

* Refusals arrive as **HTTP 200 with ``success: false``**, so the status code
  alone never tells you whether a call worked.
* ``amount`` is denominated in units where ``1000 = $1``, i.e. a cent is 10.
  This layer keeps amounts as plain ``int`` units — no Decimal/dollar
  conversion happens here.

``get_balance_units`` reads ``GET /v1/user`` and pulls the balance from
``user.wallet`` only — this shape has been verified against the live API
with a real key. No fallback shapes are accepted; a response missing that
field raises :class:`WaxpeerError` rather than risking a silently wrong
balance in a financial availability check.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from yupay.core.logging import get_logger

log = get_logger("yupay.fulfillment.waxpeer")

WaxpeerStatus = Literal["created", "sending", "completed", "canceled", "error", "unknown"]


class WaxpeerError(Exception):
    """Waxpeer refused the call (transport ok, business failure).

    ``body`` carries the raw response text, mirroring ``G2bError.body`` — the
    fulfiller that wraps this client (a later task) needs the raw payload to
    tell a real error apart from a legitimate verdict, the same way
    ``g2b_client._verdict_or_none`` re-parses ``G2bError.body``.
    """

    def __init__(self, message: str, *, status: int = 200, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class WaxpeerUnavailableError(Exception):
    """Waxpeer could not be reached at all (network error, timeout, DNS)."""


@dataclass(frozen=True)
class WaxpeerTopup:
    """One top-up as Waxpeer reports it."""

    id: int
    custom_id: str | None
    status: WaxpeerStatus
    amount_units: int
    give_amount_units: int
    steam_login: str


class WaxpeerClient:
    """Async client for the Waxpeer Steam top-up API.

    Single shared instance per process is fine — httpx pools connections
    internally. Pass ``client`` to inject a shared/mocked ``httpx.AsyncClient``
    in tests; leave it ``None`` in production to get a transient client per
    request.
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
        self._client = client  # injected in tests; None ⇒ transient per request

    @contextlib.asynccontextmanager
    async def _session(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            yield client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Issue a request and unwrap Waxpeer's ``success`` envelope.

        Returns ``(body_dict, raw_text)`` where ``raw_text`` is the original
        response body.

        Raises :class:`WaxpeerUnavailableError` on network failure,
        :class:`WaxpeerError` on HTTP >= 400 or on HTTP 200 with
        ``success: false``.
        """
        url = f"{self._base_url}{path}"
        query = {"api": self._api_key, **(params or {})}
        try:
            async with self._session() as client:
                resp = await client.request(method, url, params=query, json=json)
        except httpx.HTTPError as exc:
            log.warning("waxpeer.network_error", method=method, path=path, error=str(exc))
            raise WaxpeerUnavailableError(str(exc)) from exc

        log.info("waxpeer.request", method=method, path=path, status=resp.status_code)

        if resp.status_code >= 400:
            raise WaxpeerError(resp.text[:500], status=resp.status_code, body=resp.text)
        body: dict[str, Any] = resp.json()
        if not body.get("success", False):
            raise WaxpeerError(
                str(body.get("msg") or "waxpeer refused the request"), body=resp.text
            )
        return body, resp.text

    @staticmethod
    def _parse_topup(body: dict[str, Any]) -> WaxpeerTopup:
        raw = body.get("topup") or {}
        return WaxpeerTopup(
            id=int(raw["id"]),
            custom_id=raw.get("custom_id"),
            status=_normalise_status(raw["status"]),
            amount_units=int(raw["amount"]),
            give_amount_units=int(raw.get("give_amount", raw["amount"])),
            steam_login=str(raw.get("steam_login", "")),
        )

    async def validate_login(self, steam_login: str) -> tuple[bool, str | None]:
        """Check whether ``steam_login`` can receive a top-up.

        Returns ``(valid, reason)`` — ``reason`` is Waxpeer's ``msg`` when
        ``valid`` is ``False``, else ``None``.
        """
        body, _ = await self._request(
            "GET", "/steam-topup/validate", params={"steam_login": steam_login}
        )
        return bool(body.get("valid", False)), body.get("msg")

    async def create_topup(
        self, *, steam_login: str, amount_units: int, custom_id: str
    ) -> WaxpeerTopup:
        """Create a top-up. Raises :class:`WaxpeerError` on refusal (e.g. insufficient balance)."""
        body, _ = await self._request(
            "POST",
            "/steam-topup",
            json={
                "steam_login": steam_login,
                "amount": amount_units,
                "custom_id": custom_id,
            },
        )
        return self._parse_topup(body)

    async def get_topup(self, *, custom_id: str) -> WaxpeerTopup:
        """Look up a previously created top-up by our ``custom_id``."""
        body, _ = await self._request("GET", "/steam-topup", params={"custom_id": custom_id})
        return self._parse_topup(body)

    async def get_balance_units(self) -> int:
        """Return our Waxpeer wallet balance, in the same units as ``amount``.

        Reads ``user.wallet`` from the ``GET /v1/user`` response — this shape
        (``{"success": true, "user": {"wallet": <int>, ...}}``) has been
        verified against the live API. Raises :class:`WaxpeerError` if
        ``user.wallet`` is missing or not an ``int``, rather than risking a
        silently wrong balance in what is a financial availability check.
        """
        body, raw_text = await self._request("GET", "/user")
        user = body.get("user")
        wallet = user.get("wallet") if isinstance(user, dict) else None
        if not isinstance(wallet, int) or isinstance(wallet, bool):
            # Log the shape, never the payload: this response carries the
            # account's Steam API key and trade link. ``.body`` on the raised
            # error still has the full text for a human debugging in context.
            log.warning(
                "waxpeer.missing_wallet",
                user_keys=sorted(user) if isinstance(user, dict) else None,
                wallet_type=type(wallet).__name__,
            )
            raise WaxpeerError("/user response missing numeric user.wallet", body=raw_text)
        return wallet


def _normalise_status(raw: Any) -> WaxpeerStatus:
    """Map a raw ``topup.status`` value to :data:`WaxpeerStatus`.

    An unrecognised value must never be silently read as ``"completed"``
    (would mark undelivered goods delivered) or ``"canceled"`` (would trigger
    a refund we did not receive) — it maps to ``"unknown"`` instead, with a
    warning logged so the drift gets noticed.
    """
    known: tuple[WaxpeerStatus, ...] = (
        "created",
        "sending",
        "completed",
        "canceled",
        "error",
    )
    if raw in known:
        return raw  # type: ignore[no-any-return]
    log.warning("waxpeer.unknown_status", raw_status=raw)
    return "unknown"


__all__ = [
    "WaxpeerClient",
    "WaxpeerError",
    "WaxpeerStatus",
    "WaxpeerTopup",
    "WaxpeerUnavailableError",
]
