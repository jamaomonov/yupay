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
