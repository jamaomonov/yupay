"""Contract test for the Resend email channel (respx-mocked)."""

from __future__ import annotations

import httpx
import pytest
import respx
from yupay.core.config import get_settings

RESEND_URL = "https://api.resend.com/emails"

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _resend_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


@respx.mock
async def test_send_email_success() -> None:
    from yupay.modules.notifications.channels.email import send_email

    route = respx.post(RESEND_URL).mock(
        return_value=httpx.Response(200, json={"id": "msg_123"})
    )
    msg_id = await send_email(
        to="buyer@example.com", subject="Hi", html="<b>Hi</b>", text="Hi"
    )
    assert msg_id == "msg_123"
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer re_test_key"


@respx.mock
async def test_send_email_raises_on_4xx() -> None:
    from yupay.modules.notifications.channels.email import EmailSendError, send_email

    respx.post(RESEND_URL).mock(return_value=httpx.Response(422, json={"message": "bad"}))
    with pytest.raises(EmailSendError):
        await send_email(to="x@example.com", subject="s", html="h", text="t")


@respx.mock
async def test_send_email_raises_on_429() -> None:
    from yupay.modules.notifications.channels.email import EmailSendError, send_email

    respx.post(RESEND_URL).mock(return_value=httpx.Response(429, json={"message": "rate"}))
    with pytest.raises(EmailSendError):
        await send_email(to="x@example.com", subject="s", html="h", text="t")
