"""HTML-escaping check for the low-balance ops alert.

``_maybe_alert_low_balance`` splices supplier-controlled fields (mapping
``external_product_id`` / ``external_variant_id``, forwarded through
``FulfillResult.extra_metadata``) into a ``parse_mode:HTML`` Telegram
message. A malicious or malformed value containing HTML must come out
escaped, or it either breaks Telegram's entity parser or, worse, renders
as a spoofed alert (fake button/link) in the ops chat.
"""

from __future__ import annotations

import pytest
from yupay.core.ids import new_id
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers.base import FulfillResult

pytestmark = pytest.mark.asyncio


async def test_low_balance_alert_escapes_html_in_supplier_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Skip the Redis dedupe path entirely — it's covered elsewhere; here we
    # only care about the text handed to send_admin_alert.
    async def _no_dedupe(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(ff_svc, "_set_redis_dedupe", _no_dedupe)

    captured: list[str] = []

    async def _fake_send_admin_alert(text: str, *, kind: str = "") -> bool:
        # ``kind`` labels the alert type in the ops log; this test only cares
        # about the text, but the stub must accept the real signature.
        captured.append(text)
        return True

    import yupay.modules.notifications.api as notifications_api

    monkeypatch.setattr(notifications_api, "send_admin_alert", _fake_send_admin_alert)

    task = FulfillmentTask(
        id=new_id(),
        order_id=new_id(),
        order_item_id=new_id(),
        supplier="<b>g2b</b>",
        status="failed",
        extra_metadata={},
    )
    result = FulfillResult(
        outcome="failed",
        external_order_id=None,
        artifact_kind=None,
        artifact=None,
        error="supplier_low_balance",
        extra_metadata={
            "supplier": "<script>alert(1)</script>",
            "current_balance": "1.00",
            "required": "5.00",
            "external_product_id": '"><img src=x onerror=alert(1)>',
            "external_variant_id": "<b>60 UC</b>",
        },
        # The stall carries no money outcome — it has not finished failing.
        money_outcome=None,
    )

    await ff_svc._maybe_alert_low_balance(task=task, result=result)

    assert len(captured) == 1
    text = captured[0]
    # No raw HTML from supplier-controlled fields should survive.
    assert "<script>" not in text
    assert "<img" not in text
    assert "&lt;script&gt;" in text
    assert "&lt;b&gt;60 UC&lt;/b&gt;" in text
    assert "&quot;&gt;&lt;img src=x onerror=alert(1)&gt;" in text


async def _capture_alert(monkeypatch: pytest.MonkeyPatch, extra: dict[str, object]) -> str:
    async def _no_dedupe(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(ff_svc, "_set_redis_dedupe", _no_dedupe)
    captured: list[str] = []

    async def _fake_send_admin_alert(text: str, *, kind: str = "") -> bool:
        captured.append(text)
        return True

    import yupay.modules.notifications.api as notifications_api

    monkeypatch.setattr(notifications_api, "send_admin_alert", _fake_send_admin_alert)

    task = FulfillmentTask(
        id=new_id(),
        order_id=new_id(),
        order_item_id=new_id(),
        supplier="nova",
        status="failed",
        extra_metadata={},
    )
    result = FulfillResult(
        outcome="failed",
        external_order_id=None,
        artifact_kind=None,
        artifact=None,
        error="supplier_low_balance",
        extra_metadata=extra,
        money_outcome=None,
    )
    await ff_svc._maybe_alert_low_balance(task=task, result=result)
    assert len(captured) == 1
    return captured[0]


async def test_a_supplier_side_shortfall_does_not_tell_ops_to_top_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOVA refused a $19 Steam top-up on 2026-09-20 with "Service balance is
    insufficient" against a $112.75 wallet. The alert used to answer that with
    "Пополни счёт", sending the operator to check a balance that was fine."""
    text = await _capture_alert(
        monkeypatch,
        {
            "supplier": "nova",
            "shortfall": "supplier",
            "supplier_message": "Service balance is insufficient to complete this order",
            "current_balance": "112.7547",
        },
    )

    assert "Пополни счёт" not in text
    assert "Пополнять нечего" in text
    assert "112.7547" in text
    # Their own sentence is the evidence; it has to reach the person reading.
    assert "Service balance is insufficient" in text


async def test_our_own_shortfall_still_says_top_up(monkeypatch: pytest.MonkeyPatch) -> None:
    text = await _capture_alert(
        monkeypatch,
        {
            "supplier": "nova",
            "shortfall": "ours",
            "supplier_message": "Insufficient internal balance",
            "current_balance": "9.10",
            "required": "39.78",
        },
    )

    assert "Пополни счёт" in text
    assert "$9.10" in text
    assert "$39.78" in text


async def test_an_adapter_that_says_nothing_keeps_the_old_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only NOVA grades the side today; G2B and Waxpeer must not change."""
    text = await _capture_alert(
        monkeypatch, {"supplier": "g2b", "current_balance": "1.00", "required": "5.00"}
    )

    assert "Низкий баланс поставщика" in text
    assert "Пополни счёт" in text
