"""The UzQR POS API v1.2 wire format (ADR-0106), with respx as the transport.

Pins what the spec fixes and what we would get wrong silently: the ``Auth``
digest, the amount's text form, the error envelope, which failures mean "we
do not know" (and must be asked again) versus "UzQR said no", and that a paid
status without a ``pay_id`` is never taken as a payment.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

import httpx
import pytest
import respx
from yupay.core.config import get_settings
from yupay.modules.uzqr import client

BASE = "https://uzqr.test"


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "uzqr_base_url", BASE)
    monkeypatch.setattr(s, "uzqr_inn", "123456789")
    monkeypatch.setattr(s, "uzqr_api_key", "secret-key")
    monkeypatch.setattr(s, "uzqr_proxy_url", "")


def test_auth_header_is_inn_sha1_of_timestamp_and_key_then_timestamp() -> None:
    header = client.auth_header(inn="123456789", api_key="k", timestamp=1715000000)
    digest = hashlib.sha1(b"1715000000k").hexdigest()
    assert header == f"123456789:{digest}:1715000000"


def test_amount_goes_as_soum_with_two_decimals() -> None:
    assert client.wire_amount(Decimal(10000)) == "10000.00"
    assert client.wire_amount(Decimal("100.1")) == "100.10"


async def test_create_sends_external_id_amount_and_auth() -> None:
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/api/v1/pos/invoice/create").respond(
            200, json={"invoice_id": "INV1", "qr_text": "000201..."}
        )
        invoice = await client.create_invoice(external_id="YPABC", amount=Decimal(21000))

    assert invoice == client.Invoice(invoice_id="INV1", qr_text="000201...")
    sent = route.calls.last.request
    assert json.loads(sent.content) == {"external_id": "YPABC", "amount": "21000.00"}
    inn, digest, ts = sent.headers["Auth"].split(":")
    assert inn == "123456789"
    assert digest == hashlib.sha1(f"{ts}secret-key".encode()).hexdigest()
    assert "secret-key" not in sent.headers["Auth"]


async def test_create_without_a_qr_is_not_an_invoice() -> None:
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/v1/pos/invoice/create").respond(200, json={"invoice_id": "INV1"})
        with pytest.raises(client.UzqrUnavailableError):
            await client.create_invoice(external_id="YPABC", amount=Decimal(1000))


async def test_an_error_envelope_carries_its_code() -> None:
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/v1/pos/invoice/cancel").respond(
            400,
            json={
                "error": {
                    "error_code": 3002,
                    "message": "Invoice is already paid",
                    "user_message": "Оплата уже прошла.",
                }
            },
        )
        with pytest.raises(client.UzqrError) as caught:
            await client.cancel_invoice("INV1")
    assert caught.value.code == client.INVOICE_ALREADY_PAID
    assert caught.value.http_status == 400


async def test_a_cancel_answered_with_an_empty_200_succeeds() -> None:
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/v1/pos/invoice/cancel").respond(200)
        await client.cancel_invoice("INV1")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(502, text="bad gateway"),
        httpx.Response(200, text="<html>"),
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
    ],
)
async def test_no_usable_answer_is_unknown_not_a_refusal(
    response: httpx.Response | Exception,
) -> None:
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/api/v1/pos/invoice/status")
        if isinstance(response, Exception):
            route.mock(side_effect=response)
        else:
            route.mock(return_value=response)
        with pytest.raises(client.UzqrUnavailableError):
            await client.invoice_status("INV1")


async def test_a_paid_status_carries_the_pay_id_and_no_payer_data() -> None:
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/api/v1/pos/invoice/status").respond(
            200,
            json={
                "invoice_id": "INV1",
                "status": 2,
                "pay_id": "PAY12345678901234567",
                "payer_phone": "+998901234567",
                "card_type": "2",
                "card_no": "8600********1234",
            },
        )
        status = await client.invoice_status("INV1")
    assert route.calls.last.request.url.params["invoice_id"] == "INV1"
    assert status == client.InvoiceStatus(
        invoice_id="INV1", status=client.STATUS_PAID, pay_id="PAY12345678901234567"
    )


async def test_paid_without_a_pay_id_is_not_a_payment() -> None:
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/pos/invoice/status").respond(
            200, json={"invoice_id": "INV1", "status": 2, "pay_id": None}
        )
        with pytest.raises(client.UzqrUnavailableError):
            await client.invoice_status("INV1")


async def test_an_unknown_status_is_not_guessed() -> None:
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/pos/invoice/status").respond(
            200, json={"invoice_id": "INV1", "status": 7}
        )
        with pytest.raises(client.UzqrUnavailableError):
            await client.invoice_status("INV1")


async def test_calls_go_through_the_uz_proxy_when_one_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # uzqr.uz admits Uzbek IPs only; the VPS reaches it through a UZ proxy.
    monkeypatch.setattr(get_settings(), "uzqr_proxy_url", "http://u:p@proxy.test:3128")
    seen: dict[str, object] = {}
    real = httpx.AsyncClient

    def spy(**kwargs: object) -> httpx.AsyncClient:
        seen.update(kwargs)
        kwargs.pop("proxy")
        return real(**kwargs)  # type: ignore[arg-type]

    # `client` uses the httpx module itself, so patching it there is the same object.
    monkeypatch.setattr(httpx, "AsyncClient", spy)
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/v1/pos/invoice/cancel").respond(200)
        await client.cancel_invoice("INV1")
    assert seen["proxy"] == "http://u:p@proxy.test:3128"


async def test_a_proxy_failure_is_unknown_and_does_not_leak_its_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "uzqr_proxy_url", "http://u:secretpw@proxy.test:3128")
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/pos/invoice/status").mock(side_effect=httpx.ProxyError("refused"))
        with pytest.raises(client.UzqrUnavailableError) as caught:
            await client.invoice_status("INV1")
    assert "secretpw" not in str(caught.value)
