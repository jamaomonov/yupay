"""Guest order events trigger a transactional email.

Tests the isolated helper functions that wrap email dispatch for guest orders.
The helpers are called from within ``notify_order_paid`` and
``notify_order_delivered`` **after** the DB lookup resolves the order's
``guest_email``.  By testing the helpers directly we avoid a full DB setup
while still exercising all branching logic.
"""

from __future__ import annotations

import pytest
from yupay.modules.notifications.channels.email import EmailSendError
from yupay.modules.notifications.service import (
    _send_guest_email_confirmation,  # type: ignore[attr-defined]
    _send_guest_email_delivered,  # type: ignore[attr-defined]
)


@pytest.mark.asyncio
async def test_delivered_guest_order_sends_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """A delivered order with a guest_email triggers exactly one send_email call."""
    sent: list[dict[str, str]] = []

    async def _spy(*, to: str, subject: str, html: str, text: str) -> str:
        sent.append({"to": to, "subject": subject})
        return "msg_test"

    monkeypatch.setattr(
        "yupay.modules.notifications.service.send_email", _spy, raising=False
    )

    await _send_guest_email_delivered(
        order_id="abcdef1234",
        guest_email="guest@example.com",
        web_base="https://yupay.uz/ru",
    )

    assert len(sent) == 1
    assert sent[0]["to"] == "guest@example.com"
    assert "abcdef12" in sent[0]["subject"]


@pytest.mark.asyncio
async def test_delivered_email_embeds_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Voucher codes passed to the delivered email land in the html + text body."""
    sent: list[dict[str, str]] = []

    async def _spy(*, to: str, subject: str, html: str, text: str) -> str:
        sent.append({"to": to, "html": html, "text": text})
        return "msg_test"

    monkeypatch.setattr(
        "yupay.modules.notifications.service.send_email", _spy, raising=False
    )

    await _send_guest_email_delivered(
        order_id="abcdef1234",
        guest_email="guest@example.com",
        web_base="https://yupay.uz/ru",
        codes=["STEAM-AAAA-BBBB"],
    )

    assert len(sent) == 1
    assert "STEAM-AAAA-BBBB" in sent[0]["html"]
    assert "STEAM-AAAA-BBBB" in sent[0]["text"]


@pytest.mark.asyncio
async def test_delivery_codes_for_email_extracts_codes_and_topup() -> None:
    """The extractor returns raw voucher codes and a 'credited' line for top-ups."""
    from yupay.modules.notifications.service import (
        _delivery_codes_for_email,  # type: ignore[attr-defined]
    )

    class _D:
        def __init__(self, artifact: dict[str, object], kind: str) -> None:
            self.artifact = artifact
            self.artifact_kind = kind

    rows = [
        _D({"code": "VOUCHER-1"}, "voucher_code"),
        _D({"key": "LICENSE-2"}, "license_key"),
        _D({"fulfillment_data": {"player_id": "42"}}, "topup_receipt"),
    ]
    lines = _delivery_codes_for_email(rows)  # type: ignore[arg-type]
    assert lines == ["VOUCHER-1", "LICENSE-2", "Зачислено на ваш аккаунт"]


@pytest.mark.asyncio
async def test_delivered_no_guest_email_skips_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """A delivered order without a guest_email must NOT call send_email."""
    sent: list[dict[str, str]] = []

    async def _spy(*, to: str, subject: str, html: str, text: str) -> str:  # pragma: no cover
        sent.append({"to": to, "subject": subject})
        return "msg_test"

    monkeypatch.setattr(
        "yupay.modules.notifications.service.send_email", _spy, raising=False
    )

    await _send_guest_email_delivered(
        order_id="abcdef1234",
        guest_email=None,
        web_base="https://yupay.uz/ru",
    )

    assert sent == []


@pytest.mark.asyncio
async def test_delivered_no_web_base_skips_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """A delivered order with an empty web_base must NOT call send_email (dev guard)."""
    sent: list[dict[str, str]] = []

    async def _spy(*, to: str, subject: str, html: str, text: str) -> str:  # pragma: no cover
        sent.append({"to": to, "subject": subject})
        return "msg_test"

    monkeypatch.setattr(
        "yupay.modules.notifications.service.send_email", _spy, raising=False
    )

    await _send_guest_email_delivered(
        order_id="abcdef1234",
        guest_email="guest@example.com",
        web_base="",
    )

    assert sent == []


@pytest.mark.asyncio
async def test_confirmation_guest_order_sends_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """A paid order with a guest_email triggers exactly one confirmation send_email call."""
    sent: list[dict[str, str]] = []

    async def _spy(*, to: str, subject: str, html: str, text: str) -> str:
        sent.append({"to": to, "subject": subject})
        return "msg_test"

    monkeypatch.setattr(
        "yupay.modules.notifications.service.send_email", _spy, raising=False
    )

    await _send_guest_email_confirmation(
        order_id="abcdef1234",
        guest_email="guest@example.com",
        web_base="https://yupay.uz/ru",
    )

    assert len(sent) == 1
    assert sent[0]["to"] == "guest@example.com"
    assert "abcdef12" in sent[0]["subject"]


@pytest.mark.asyncio
async def test_confirmation_no_guest_email_skips_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """A paid order without a guest_email must NOT call send_email."""
    sent: list[dict[str, str]] = []

    async def _spy(*, to: str, subject: str, html: str, text: str) -> str:  # pragma: no cover
        sent.append({"to": to, "subject": subject})
        return "msg_test"

    monkeypatch.setattr(
        "yupay.modules.notifications.service.send_email", _spy, raising=False
    )

    await _send_guest_email_confirmation(
        order_id="abcdef1234",
        guest_email=None,
        web_base="https://yupay.uz/ru",
    )

    assert sent == []


@pytest.mark.asyncio
async def test_email_send_error_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """EmailSendError from the channel must never propagate (best-effort contract)."""

    async def _fail(*, to: str, subject: str, html: str, text: str) -> str:
        raise EmailSendError("resend returned 503")

    monkeypatch.setattr(
        "yupay.modules.notifications.service.send_email", _fail, raising=False
    )

    # Must not raise.
    await _send_guest_email_delivered(
        order_id="abcdef1234",
        guest_email="guest@example.com",
        web_base="https://yupay.uz/ru",
    )
