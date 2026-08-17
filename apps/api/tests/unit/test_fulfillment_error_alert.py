"""Every fulfilment error reaches the ops chat, and only once per incident.

Errors used to be visible only by opening the admin — a supplier that started
refusing every order announced itself by a customer complaining. This alerts
from ``_record_attempt``, which is the single place all of them pass through:
a call that threw and a call that succeeded while *reporting* failure both
record ``status="error"``.
"""

from __future__ import annotations

import pytest
from yupay.core.ids import new_id
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.fulfillment.models import FulfillmentTask

pytestmark = pytest.mark.asyncio


def _task() -> FulfillmentTask:
    return FulfillmentTask(
        id=new_id(),
        order_id=new_id(),
        order_item_id=new_id(),
        supplier="waxpeer",
        status="in_progress",
        extra_metadata={},
    )


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture alerts, with the Redis dedupe stubbed to "never seen"."""
    captured: list[str] = []

    async def _no_dedupe(*_a: object, **_kw: object) -> bool:
        return False

    async def _send(text: str, *, kind: str = "") -> bool:
        captured.append(text)
        return True

    import yupay.modules.notifications.api as notifications_api

    monkeypatch.setattr(ff_svc, "_set_redis_dedupe", _no_dedupe)
    monkeypatch.setattr(notifications_api, "send_admin_alert", _send)
    return captured


async def test_an_error_is_announced_with_what_is_needed_to_act(sent: list[str]) -> None:
    task = _task()
    await ff_svc._alert_fulfillment_error(task, kind="fulfill", error="HTTP 502 from supplier")

    assert len(sent) == 1
    text = sent[0]
    assert "Ошибка фулфилмента" in text
    assert "fulfill" in text
    assert "waxpeer" in text
    assert task.order_id in text
    assert "HTTP 502 from supplier" in text


async def test_supplier_text_is_escaped_before_going_into_an_html_message(
    sent: list[str],
) -> None:
    # Same hazard the low-balance alert guards: supplier-controlled text in a
    # parse_mode:HTML message either breaks Telegram's parser or renders a
    # spoofed alert in the ops chat.
    task = _task()
    task.supplier = "<b>waxpeer</b>"
    await ff_svc._alert_fulfillment_error(task, kind="fulfill", error="<a href=x>click</a>")

    text = sent[0]
    assert "<a href=x>" not in text
    assert "&lt;a href=x&gt;" in text
    assert "<b>waxpeer</b>" not in text.replace("<b>🛑 Ошибка фулфилмента</b>", "")


async def test_a_missing_error_string_still_alerts(sent: list[str]) -> None:
    # `error` is nullable; a failure with no text is still a failure and must
    # not be silently dropped.
    await ff_svc._alert_fulfillment_error(_task(), kind="status_check", error=None)

    assert len(sent) == 1
    assert "без текста ошибки" in sent[0]


async def test_a_long_error_is_truncated_rather_than_flooding_the_chat(
    sent: list[str],
) -> None:
    await ff_svc._alert_fulfillment_error(_task(), kind="fulfill", error="x" * 5000)

    assert len(sent[0]) < 1000


async def test_the_same_error_on_the_same_task_is_announced_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stuck task retries on a schedule; ops needs telling once, not hourly
    forever within the window."""
    seen: set[str] = set()

    async def _dedupe(key: str, *, ttl_seconds: int) -> bool:
        existed = key in seen
        seen.add(key)
        return existed

    captured: list[str] = []

    async def _send(text: str, *, kind: str = "") -> bool:
        captured.append(text)
        return True

    import yupay.modules.notifications.api as notifications_api

    monkeypatch.setattr(ff_svc, "_set_redis_dedupe", _dedupe)
    monkeypatch.setattr(notifications_api, "send_admin_alert", _send)

    task = _task()
    for _ in range(4):
        await ff_svc._alert_fulfillment_error(task, kind="fulfill", error="same failure")
    assert len(captured) == 1

    # A *different* failure is a different incident and speaks up.
    await ff_svc._alert_fulfillment_error(task, kind="fulfill", error="another failure")
    assert len(captured) == 2


async def test_an_alerting_outage_cannot_fail_the_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The saga is mid-transaction here. A dead Telegram must cost us the
    notification, never the sale."""

    async def _no_dedupe(*_a: object, **_kw: object) -> bool:
        return False

    async def _explode(*_a: object, **_kw: object) -> bool:
        raise RuntimeError("telegram is down")

    import yupay.modules.notifications.api as notifications_api

    monkeypatch.setattr(ff_svc, "_set_redis_dedupe", _no_dedupe)
    monkeypatch.setattr(notifications_api, "send_admin_alert", _explode)

    # Must not raise.
    await ff_svc._alert_fulfillment_error(_task(), kind="fulfill", error="boom")
