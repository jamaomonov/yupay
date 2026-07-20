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

``get_balance_units`` is defensive about the ``GET /v1/user`` response shape:
we have only the recorded docs shape (``user.wallet``), never a live-API
capture, so it also accepts a top-level ``wallet`` or ``balance`` key as
fallbacks. See the module docstring in the contract test for the rationale.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from yupay.core.logging import get_logger

log = get_logger("yupay.fulfillment.waxpeer")

WaxpeerStatus = Literal["created", "sending", "completed", "canceled", "error"]


class WaxpeerError(Exception):
    """Waxpeer refused the call (transport ok, business failure)."""

    def __init__(self, message: str, *, status: int = 200) -> None:
        super().__init__(message)
        self.status = status


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
    ) -> dict[str, Any]:
        """Issue a request and unwrap Waxpeer's ``success`` envelope.

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
            raise WaxpeerError(resp.text[:500], status=resp.status_code)
        body: dict[str, Any] = resp.json()
        if not body.get("success", False):
            raise WaxpeerError(str(body.get("msg") or "waxpeer refused the request"))
        return body

    @staticmethod
    def _parse_topup(body: dict[str, Any]) -> WaxpeerTopup:
        raw = body.get("topup") or {}
        return WaxpeerTopup(
            id=int(raw["id"]),
            custom_id=raw.get("custom_id"),
            status=raw["status"],
            amount_units=int(raw["amount"]),
            give_amount_units=int(raw.get("give_amount", raw["amount"])),
            steam_login=str(raw.get("steam_login", "")),
        )

    async def validate_login(self, steam_login: str) -> tuple[bool, str | None]:
        """Check whether ``steam_login`` can receive a top-up.

        Returns ``(valid, reason)`` — ``reason`` is Waxpeer's ``msg`` when
        ``valid`` is ``False``, else ``None``.
        """
        body = await self._request(
            "GET", "/steam-topup/validate", params={"steam_login": steam_login}
        )
        return bool(body.get("valid", False)), body.get("msg")

    async def create_topup(
        self, *, steam_login: str, amount_units: int, custom_id: str
    ) -> WaxpeerTopup:
        """Create a top-up. Raises :class:`WaxpeerError` on refusal (e.g. insufficient balance)."""
        body = await self._request(
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
        body = await self._request("GET", "/steam-topup", params={"custom_id": custom_id})
        return self._parse_topup(body)

    async def get_balance_units(self) -> int:
        """Return our Waxpeer wallet balance, in the same units as ``amount``.

        The real ``GET /v1/user`` payload shape has never been observed
        against the live API — only the recorded docs shape
        (``{"user": {"wallet": ...}}``). To avoid silently misreading an
        unrecognised shape as a zero balance, this checks, in order,
        ``user.wallet``, top-level ``wallet``, then top-level ``balance``,
        and raises :class:`WaxpeerError` if none of them is present and
        numeric.
        """
        body = await self._request("GET", "/user")
        user = body.get("user")
        candidates: tuple[Any, ...] = (
            user.get("wallet") if isinstance(user, dict) else None,
            body.get("wallet"),
            body.get("balance"),
        )
        for candidate in candidates:
            if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
                return int(candidate)
        raise WaxpeerError(
            "unrecognised /user response shape: no numeric balance in "
            "user.wallet, wallet, or balance"
        )


__all__ = [
    "WaxpeerClient",
    "WaxpeerError",
    "WaxpeerStatus",
    "WaxpeerTopup",
    "WaxpeerUnavailableError",
]
