"""The three merchant money alerts, executed (M3b Task 3).

The integration suite replaces ``_dispatch_alert`` with a recorder, so it
proves *which* alert fires and never runs one. These bodies splice values into
a ``parse_mode:HTML`` Telegram message and are the only place an operator
learns that a reseller's deposit needs a decision, so they get the same
treatment ``test_fulfillment_low_balance_alert.py`` gives its own: run them,
read the text, and check the two things that can go wrong in a message nobody
reads until it matters.

* **Escaping.** ``supplier`` and a cancel ``reason`` are free text — a slug an
  operator typed, an admin note — and unescaped HTML either breaks Telegram's
  entity parser or renders as a spoofed alert with a working link.
* **PII.** AGENTS.md §9: order ids, task ids, supplier slugs and amounts are
  fine; nothing else may appear. These messages are built from arguments, so
  the assertion that holds is that the arguments are *all* that is there.

The dedupe is checked too, because these three are the fan-out cases: a
supplier outage parks fifty orders in a minute, and the window is the only
thing between that and fifty identical messages.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from yupay.core.ids import new_id
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.fulfillment.suppliers.base import MoneyOutcome

pytestmark = pytest.mark.asyncio

#: A no-argument thunk that returns one of the three alert coroutines. The
#: "every alert" cases below are about a property all three share, so the list
#: is written once and reused rather than restated per test — a third alert
#: added without a row here is the failure mode that costs.
type Alert = Callable[[], Coroutine[Any, Any, None]]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Capture ``(text, kind)`` and skip the Redis dedupe."""
    captured: list[tuple[str, str]] = []

    async def _no_dedupe(*_args: object, **_kwargs: object) -> bool:
        return False

    async def _send(text: str, *, kind: str = "") -> bool:
        captured.append((text, kind))
        return True

    import yupay.modules.notifications.api as notifications_api

    monkeypatch.setattr(ff_svc, "_set_redis_dedupe", _no_dedupe)
    monkeypatch.setattr(notifications_api, "send_admin_alert", _send)
    return captured


@pytest.mark.parametrize(
    ("outcome", "phrase"),
    [(MoneyOutcome.SPENT, "оставил деньги"), (MoneyOutcome.UNKNOWN, "выяснить нельзя")],
)
async def test_the_needs_a_human_alert_says_which_of_the_two_it_is(
    sent: list[tuple[str, str]], outcome: MoneyOutcome, phrase: str
) -> None:
    """``SPENT`` and ``UNKNOWN`` refund nothing either way, but they send a
    person to do different things — one to chase our money, one to find out
    what happened. The alert is the only place that distinction reaches them.
    """
    order_id, task_id = new_id(), new_id()
    await ff_svc._alert_merchant_needs_a_human(
        task_id=task_id, order_id=order_id, supplier="waxpeer", outcome=outcome
    )

    assert len(sent) == 1
    text, kind = sent[0]
    assert kind == "merchant_money_outcome"
    assert phrase in text
    assert outcome.value in text
    assert order_id in text
    assert task_id in text


async def test_the_needs_a_human_alert_escapes_a_supplier_slug(
    sent: list[tuple[str, str]],
) -> None:
    """The slug is free text an operator typed into a mapping."""
    await ff_svc._alert_merchant_needs_a_human(
        task_id=new_id(),
        order_id=new_id(),
        supplier="<script>alert(1)</script>",
        outcome=MoneyOutcome.SPENT,
    )

    text = sent[0][0]
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


async def test_the_refund_failed_alert_carries_the_order_and_clips_the_error(
    sent: list[tuple[str, str]],
) -> None:
    """The order id is what an operator settles by, so it is the one thing
    this message cannot be useful without. The error is clipped because a
    driver message can be a wall of chat."""
    order_id, task_id = new_id(), new_id()
    await ff_svc._alert_merchant_refund_failed(
        task_id=task_id, order_id=order_id, error="<b>boom</b> " + "x" * 900
    )

    text, kind = sent[0]
    assert kind == "merchant_refund_failed"
    assert order_id in text
    assert task_id in text
    assert "<b>boom</b>" not in text  # escaped, not rendered
    assert "&lt;b&gt;boom&lt;/b&gt;" in text
    assert len(text) < 900  # the 300-char clip did its job


async def test_the_cancelled_alert_escapes_the_operators_reason(
    sent: list[tuple[str, str]],
) -> None:
    """``reason`` reaches here from an admin's own words."""
    order_id = new_id()
    await ff_svc._alert_merchant_order_cancelled(
        task_id=new_id(), order_id=order_id, reason='"><img src=x onerror=alert(1)>'
    )

    text, kind = sent[0]
    assert kind == "merchant_order_cancelled"
    assert order_id in text
    assert "<img" not in text
    assert "&lt;img src=x onerror=alert(1)&gt;" in text


@pytest.mark.parametrize(
    "call",
    _EVERY_ALERT := [
        lambda: ff_svc._alert_merchant_needs_a_human(
            task_id="t", order_id="o", supplier="g2b", outcome=MoneyOutcome.UNKNOWN
        ),
        lambda: ff_svc._alert_merchant_refund_failed(task_id="t", order_id="o", error="e"),
        lambda: ff_svc._alert_merchant_order_cancelled(task_id="t", order_id="o", reason="r"),
    ],
)
async def test_a_deduped_alert_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]], call: Alert
) -> None:
    """The window is the whole defence against a supplier outage fanning fifty
    parked orders into fifty identical messages."""

    async def _already_alerted(*_args: object, **_kwargs: object) -> bool:
        return True

    monkeypatch.setattr(ff_svc, "_set_redis_dedupe", _already_alerted)
    await call()

    assert sent == []


@pytest.mark.parametrize("call", _EVERY_ALERT)
async def test_an_alerting_outage_never_escapes(
    monkeypatch: pytest.MonkeyPatch, call: Alert
) -> None:
    """An alert runs inside the saga's transaction on the money path. If it
    could raise, a Telegram outage would be able to fail an order that is
    otherwise fine — which is why all three swallow and log instead."""

    async def _no_dedupe(*_args: object, **_kwargs: object) -> bool:
        return False

    async def _explode(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("telegram is down")

    import yupay.modules.notifications.api as notifications_api

    monkeypatch.setattr(ff_svc, "_set_redis_dedupe", _no_dedupe)
    monkeypatch.setattr(notifications_api, "send_admin_alert", _explode)

    await call()
