"""Expo's push service: ``/push/send`` and ``/push/getReceipts``.

Expo relays to APNs and FCM, so the app needs no Apple or Google push keys of its own here —
those live in the Expo project (EAS credentials). ``EXPO_ACCESS_TOKEN`` is optional: set, it
is sent as a bearer and Expo's «enhanced push security» refuses anyone else's sends to our
tokens.

Called by the worker and the scheduler only, never from a request handler (AGENTS.md §10).
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from yupay.core.config import get_settings

SEND_URL: Final = "https://exp.host/--/api/v2/push/send"
RECEIPTS_URL: Final = "https://exp.host/--/api/v2/push/getReceipts"
#: Expo accepts at most 100 messages per send and 1000 ids per receipts call.
SEND_BATCH: Final = 100
RECEIPTS_BATCH: Final = 1000
_TIMEOUT: Final = httpx.Timeout(10.0)


class ExpoUnavailableError(Exception):
    """The request as a whole failed: network, 429 or 5xx. Worth retrying later."""

    def __init__(self, reason: str, *, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(reason)


class ExpoRejectedError(Exception):
    """A 4xx other than 429: the request itself is wrong and will not get better."""


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    token = get_settings().expo_access_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _retry_after(res: httpx.Response) -> float | None:
    try:
        return float(res.headers.get("Retry-After", ""))
    except ValueError:
        return None


async def _post(url: str, payload: object) -> Any:  # Any: Expo's JSON envelope
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
            res = await client.post(url, json=payload, headers=_headers())
    except httpx.HTTPError as exc:
        raise ExpoUnavailableError(type(exc).__name__) from exc
    if res.status_code == 429 or res.status_code >= 500:
        raise ExpoUnavailableError(f"http {res.status_code}", retry_after=_retry_after(res))
    if res.status_code >= 400:
        raise ExpoRejectedError(f"http {res.status_code}")
    try:
        return res.json()
    except ValueError as exc:
        raise ExpoUnavailableError("bad json") from exc


async def send(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Send up to :data:`SEND_BATCH` messages; one ticket per message, in the same order.

    A ticket is ``{"status": "ok", "id": …}`` or ``{"status": "error", "details": {"error": …}}``.
    """
    body = await _post(SEND_URL, messages)
    tickets = body.get("data") if isinstance(body, dict) else None
    if not isinstance(tickets, list) or len(tickets) != len(messages):
        raise ExpoUnavailableError("tickets do not match the messages")
    return [t if isinstance(t, dict) else {"status": "error"} for t in tickets]


async def receipts(ticket_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Receipts by ticket id. A ticket missing from the answer has no receipt yet."""
    body = await _post(RECEIPTS_URL, {"ids": ticket_ids})
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise ExpoUnavailableError("no receipts object")
    return {k: v for k, v in data.items() if isinstance(v, dict)}
