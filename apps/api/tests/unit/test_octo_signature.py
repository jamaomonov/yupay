"""Unit tests for the Octo gateway's pure logic: signature, status mapping,
currency guard, webhook verification, and secret redaction.

No DB, no HTTP — :class:`OctoGateway.create_intent` currency rejection and
``verify_webhook`` are exercised against in-memory objects.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from yupay.core import config as cfg
from yupay.core.logging import REDACTED_KEYS, _redact_pii
from yupay.modules.payments.gateways.base import PaymentGatewayError
from yupay.modules.payments.gateways.octo import (
    OctoClient,
    OctoGateway,
    _map_status,
    compute_signature,
)

UNIQUE_KEY = "e27d3f79-3189-44e9-8a66-566a141025df"
UUID = "4556a13e-f763-4b91-9387-92395fd51ccf"


@pytest.fixture
def _octo_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OCTO_SHOP_ID", "123")
    monkeypatch.setenv("OCTO_SECRET", "shop-secret")
    monkeypatch.setenv("OCTO_SIGNATURE_KEY", UNIQUE_KEY)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def test_compute_signature_matches_sha1_formula() -> None:
    expected = hashlib.sha1(f"{UNIQUE_KEY}{UUID}succeeded".encode()).hexdigest()
    assert compute_signature(UNIQUE_KEY, UUID, "succeeded") == expected
    # lowercase hex, 40 chars
    assert len(compute_signature(UNIQUE_KEY, UUID, "succeeded")) == 40


def test_map_status() -> None:
    assert _map_status("succeeded") == "succeeded"
    assert _map_status("canceled") == "cancelled"
    assert _map_status("cancelled") == "cancelled"
    assert _map_status("failed") == "failed"
    assert _map_status("expired") == "failed"
    # intermediate / unknown → pending (no-op)
    assert _map_status("created") == "pending"
    assert _map_status("waiting_for_capture") == "pending"
    assert _map_status("wait_user_action") == "pending"
    assert _map_status("something_new") == "pending"


def test_secrets_are_redacted_in_logs() -> None:
    assert "octo_secret" in REDACTED_KEYS
    assert "octo_signature_key" in REDACTED_KEYS
    event = _redact_pii(
        None,
        "info",
        {"octo_secret": "shop-secret", "octo_signature_key": UNIQUE_KEY, "order_id": "ok"},
    )
    assert event["octo_secret"] == "<redacted>"
    assert event["octo_signature_key"] == "<redacted>"
    assert event["order_id"] == "ok"  # non-sensitive passes through


@pytest.mark.asyncio
async def test_create_intent_rejects_unsupported_currency(_octo_env: None) -> None:
    # Inject a client so no HTTP is attempted (the currency guard fires first).
    gw = OctoGateway(client=OctoClient(shop_id="123", secret="s", base_url="https://octo.test"))
    order = SimpleNamespace(id="ord-1", currency="EUR", total_charged=Decimal("100.00"))
    with pytest.raises(PaymentGatewayError, match="currency"):
        await gw.create_intent(db=cast(Any, None), order=order, return_url="")


@pytest.mark.asyncio
async def test_verify_webhook_accepts_valid_signature(_octo_env: None) -> None:
    gw = OctoGateway()
    sig = compute_signature(UNIQUE_KEY, UUID, "succeeded").upper()  # Octo sends UPPERCASE
    body = json.dumps({"octo_payment_UUID": UUID, "status": "succeeded", "signature": sig}).encode()
    event = await gw.verify_webhook(headers={}, body=body)
    assert event.outcome == "succeeded"
    assert event.external_payment_id == UUID
    assert event.external_event_id == f"{UUID}:succeeded"


@pytest.mark.asyncio
async def test_verify_webhook_rejects_bad_signature(_octo_env: None) -> None:
    gw = OctoGateway()
    body = json.dumps(
        {"octo_payment_UUID": UUID, "status": "succeeded", "signature": "deadbeef"}
    ).encode()
    with pytest.raises(PaymentGatewayError, match="signature"):
        await gw.verify_webhook(headers={}, body=body)


@pytest.mark.asyncio
async def test_verify_webhook_refuses_when_key_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCTO_SHOP_ID", "123")
    monkeypatch.setenv("OCTO_SECRET", "shop-secret")
    monkeypatch.setenv("OCTO_SIGNATURE_KEY", "")
    cfg.get_settings.cache_clear()
    try:
        gw = OctoGateway()
        body = json.dumps({"octo_payment_UUID": UUID, "status": "succeeded"}).encode()
        with pytest.raises(PaymentGatewayError, match="signature key not configured"):
            await gw.verify_webhook(headers={}, body=body)
    finally:
        cfg.get_settings.cache_clear()
