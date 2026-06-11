"""Stub adapters, registries and trivial fulfillers — every refusal path.

Stubs reserve provider/supplier slugs and must refuse loudly, not pretend.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import pytest
from yupay.core.errors import NotFoundError
from yupay.modules.fulfillment.suppliers import (
    REGISTRY as SUPPLIERS,
)
from yupay.modules.fulfillment.suppliers import (
    available_suppliers,
    get_fulfiller,
)
from yupay.modules.fulfillment.suppliers._stub import StubFulfiller
from yupay.modules.fulfillment.suppliers.base import FulfillerNotIntegratedError
from yupay.modules.fulfillment.suppliers.manual import ManualFulfiller
from yupay.modules.fulfillment.suppliers.mock import MockFulfiller
from yupay.modules.payments.gateways import REGISTRY as GATEWAYS
from yupay.modules.payments.gateways import get_gateway
from yupay.modules.payments.gateways._stub import StubGateway
from yupay.modules.payments.gateways.base import PaymentGatewayError, PaymentNotIntegratedError
from yupay.modules.payments.gateways.wallet import WalletGateway

pytestmark = pytest.mark.asyncio

_DB = cast(Any, None)


async def test_stub_fulfiller_refuses_everything() -> None:
    stub = StubFulfiller(supplier="steam", todo_message="steam pending")
    assert stub.available is False
    with pytest.raises(FulfillerNotIntegratedError, match="steam pending"):
        await stub.fulfill(db=_DB, order=_DB, item=_DB, idempotency_key="k")
    with pytest.raises(FulfillerNotIntegratedError):
        await stub.check_status(db=_DB, task=_DB)
    with pytest.raises(FulfillerNotIntegratedError):
        await stub.cancel(db=_DB, task=_DB)


async def test_stub_gateway_refuses_everything() -> None:
    stub = StubGateway(provider="click", todo_message="click pending")
    assert stub.available is False
    with pytest.raises(PaymentNotIntegratedError, match="click pending"):
        await stub.create_intent(db=_DB, order=_DB, return_url="")
    with pytest.raises(PaymentNotIntegratedError):
        await stub.verify_webhook(headers={}, body=b"{}")
    with pytest.raises(PaymentNotIntegratedError):
        await stub.refund(payment=_DB, amount=Decimal("1"))


def test_supplier_registry_lookup() -> None:
    assert get_fulfiller("MOCK").supplier == "mock"
    with pytest.raises(NotFoundError, match="unknown fulfilment supplier"):
        get_fulfiller("definitely-not-a-supplier")
    live = available_suppliers()
    assert "manual" in live
    # Stub slugs are registered but never reported as available.
    assert all(slug in SUPPLIERS for slug in live)


def test_gateway_registry_lookup() -> None:
    assert get_gateway("mock").provider == "mock"
    with pytest.raises(NotFoundError):
        get_gateway("definitely-not-a-provider")
    assert "click" in GATEWAYS  # stub slug stays reserved


async def test_manual_fulfiller_is_human_shaped() -> None:
    manual = ManualFulfiller()
    assert manual.available is True
    status = await manual.check_status(db=_DB, task=_DB)
    assert status.outcome == "in_progress"
    await manual.cancel(db=_DB, task=_DB)  # not raising IS the contract


async def test_mock_fulfiller_status_and_cancel() -> None:
    mock = MockFulfiller()
    status = await mock.check_status(db=_DB, task=_DB)
    assert status.outcome == "succeeded"
    await mock.cancel(db=_DB, task=_DB)  # not raising IS the contract


async def test_wallet_gateway_has_no_webhook() -> None:
    with pytest.raises(PaymentGatewayError, match="no inbound webhook"):
        await WalletGateway().verify_webhook(headers={}, body=b"{}")
