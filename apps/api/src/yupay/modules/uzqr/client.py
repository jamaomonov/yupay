"""HTTP client for the UzQR POS API v1.2 (ADR-0106).

UzQR is the Central Bank's single-QR scheme: the merchant registers a dynamic
QR in uzqr.uz, and a "POS" — here, our server — asks for one invoice per
payment and polls it. There is no callback; polling is the spec's only way to
learn about a payment (§2.4.5).

Only the three methods the storefront needs are wrapped: create, status and
cancel. Reconciliation is the operator's (uzqr.uz «История операций»), and
refunds are left out on purpose — UzQR
has them switched off at the time of writing, and a refund we cannot confirm
is worse than one an operator does from the bank.

The payer's phone and masked card come back on a paid status. They are PII we
have no use for, so :class:`InvoiceStatus` does not carry them.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

import httpx

from yupay.core.config import get_settings

#: Spec §2.4.2: one status vocabulary for invoices, refunds and payments.
STATUS_PENDING: Final = 1
STATUS_PAID: Final = 2
STATUS_REJECTED: Final = 3

#: Spec §2.7.2.
INVOICE_NOT_FOUND: Final = 3001
INVOICE_ALREADY_PAID: Final = 3002


class UzqrError(Exception):
    """UzQR answered, and the answer was an error.

    Attributes:
        code: ``error.error_code`` from the body, ``None`` when there was none.
        http_status: The HTTP status of the response.
    """

    def __init__(self, message: str, *, code: int | None, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class UzqrUnavailableError(Exception):
    """No usable answer: transport failure, timeout, a 5xx or a body we cannot read.

    The outcome of the request is unknown — a create may have made an invoice,
    a cancel may have cancelled. Callers treat it as "ask again later".
    """


@dataclass(frozen=True)
class Invoice:
    """What ``invoice/create`` returns."""

    invoice_id: str
    qr_text: str


@dataclass(frozen=True)
class InvoiceStatus:
    """What ``invoice/status`` returns, minus the payer's PII."""

    invoice_id: str
    status: int
    pay_id: str | None


def auth_header(*, inn: str, api_key: str, timestamp: int) -> str:
    """``Auth: INN:sha1(timestamp + API_key):timestamp`` (spec §2.2)."""
    digest = hashlib.sha1(f"{timestamp}{api_key}".encode(), usedforsecurity=False).hexdigest()
    return f"{inn}:{digest}:{timestamp}"


def wire_amount(amount: Decimal) -> str:
    """Soʻm with a dot and two decimals, e.g. ``"10000.00"`` (spec §2.4.1)."""
    return f"{amount.quantize(Decimal('0.01')):f}"


async def _call(
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    settings = get_settings()
    headers = {
        "Auth": auth_header(
            inn=settings.uzqr_inn, api_key=settings.uzqr_api_key, timestamp=int(time.time())
        )
    }
    try:
        async with httpx.AsyncClient(
            base_url=settings.uzqr_base_url,
            timeout=settings.uzqr_request_timeout_seconds,
            proxy=settings.uzqr_proxy_url or None,
        ) as client:
            resp = await client.request(method, path, params=params, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise UzqrUnavailableError(f"uzqr {path}: {type(exc).__name__}") from exc
    if resp.status_code >= 500:
        raise UzqrUnavailableError(f"uzqr {path}: HTTP {resp.status_code}")
    if not resp.content:
        if resp.is_success:
            return None
        raise UzqrError(
            f"uzqr {path}: HTTP {resp.status_code}", code=None, http_status=resp.status_code
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise UzqrUnavailableError(f"uzqr {path}: unreadable body") from exc
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        code = error.get("error_code")
        raise UzqrError(
            f"uzqr {path}: {error.get('message') or 'error'}",
            code=code if isinstance(code, int) else None,
            http_status=resp.status_code,
        )
    if not resp.is_success or not isinstance(data, dict):
        raise UzqrError(
            f"uzqr {path}: HTTP {resp.status_code}", code=None, http_status=resp.status_code
        )
    return data


async def create_invoice(*, external_id: str, amount: Decimal) -> Invoice:
    """``POST /api/v1/pos/invoice/create``.

    ``external_id`` makes a repeat of the same request a replay until the
    invoice is final (spec §2.3.2), so retrying after a timeout is safe.
    """
    data = await _call(
        "POST",
        "/api/v1/pos/invoice/create",
        body={"external_id": external_id, "amount": wire_amount(amount)},
    )
    invoice_id = (data or {}).get("invoice_id")
    qr_text = (data or {}).get("qr_text")
    if (
        not isinstance(invoice_id, str)
        or not invoice_id
        or not isinstance(qr_text, str)
        or not qr_text
    ):
        raise UzqrUnavailableError("uzqr invoice/create: no invoice_id or qr_text")
    return Invoice(invoice_id=invoice_id, qr_text=qr_text)


async def invoice_status(invoice_id: str) -> InvoiceStatus:
    """``GET /api/v1/pos/invoice/status``."""
    data = await _call("GET", "/api/v1/pos/invoice/status", params={"invoice_id": invoice_id})
    raw = (data or {}).get("status")
    try:
        status = int(raw)  # type: ignore[arg-type]  # validated just below
    except (TypeError, ValueError) as exc:
        raise UzqrUnavailableError(f"uzqr invoice/status: bad status {raw!r}") from exc
    if status not in (STATUS_PENDING, STATUS_PAID, STATUS_REJECTED):
        raise UzqrUnavailableError(f"uzqr invoice/status: unknown status {status}")
    pay_id = (data or {}).get("pay_id")
    if status == STATUS_PAID and not (isinstance(pay_id, str) and pay_id):
        # Paid without a payment id is not something we can book against.
        raise UzqrUnavailableError("uzqr invoice/status: paid without pay_id")
    return InvoiceStatus(
        invoice_id=invoice_id,
        status=status,
        pay_id=pay_id if isinstance(pay_id, str) and pay_id else None,
    )


async def cancel_invoice(invoice_id: str) -> None:
    """``POST /api/v1/pos/invoice/cancel``.

    Raises:
        UzqrError: with ``code == INVOICE_ALREADY_PAID`` when the payer beat us
            to it — the caller must then read the status and book the payment.
    """
    await _call("POST", "/api/v1/pos/invoice/cancel", body={"invoice_id": invoice_id})


__all__ = [
    "INVOICE_ALREADY_PAID",
    "INVOICE_NOT_FOUND",
    "STATUS_PAID",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "Invoice",
    "InvoiceStatus",
    "UzqrError",
    "UzqrUnavailableError",
    "auth_header",
    "cancel_invoice",
    "create_invoice",
    "invoice_status",
    "wire_amount",
]
