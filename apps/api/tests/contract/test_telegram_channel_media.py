"""Contract tests for the Telegram broadcast media senders (respx-mocked).

Covers ``send_broadcast_message`` — the single entry point the scheduler
dispatch job and the admin test-send route use to post a broadcast (text or
one media attachment) and capture the Telegram ``file_id`` for reuse.
"""

from __future__ import annotations

import json

import httpx
import respx
from yupay.modules.notifications.channels.telegram import (
    SendOutcome,
    send_broadcast_message,
)

BOT_TOKEN = "123456:TEST-TOKEN"
CHAT_ID = 42
_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


@respx.mock
async def test_none_media_type_posts_send_message_with_text_and_html() -> None:
    route = respx.post(f"{_BASE}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    )

    outcome = await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="<b>Hello</b>",
        media_type="none",
        media_url_or_file_id=None,
    )

    assert outcome == SendOutcome(ok=True, file_id=None, status=200)
    assert route.called
    assert route.calls.last.request.url == f"{_BASE}/sendMessage"
    payload = _json_body(route)
    assert payload["chat_id"] == CHAT_ID
    assert payload["text"] == "<b>Hello</b>"
    assert payload["parse_mode"] == "HTML"
    assert payload["disable_web_page_preview"] is True


@respx.mock
async def test_photo_media_type_posts_send_photo_and_captures_last_file_id() -> None:
    route = respx.post(f"{_BASE}/sendPhoto").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "photo": [
                        {"file_id": "small", "width": 90, "height": 90},
                        {"file_id": "F", "width": 800, "height": 800},
                    ]
                },
            },
        )
    )

    outcome = await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="<i>caption</i>",
        media_type="photo",
        media_url_or_file_id="https://cdn.yupay.uz/broadcasts/pic.jpg",
    )

    assert outcome.ok is True
    assert outcome.file_id == "F"
    assert outcome.status == 200
    assert route.called
    payload = _json_body(route)
    assert payload["photo"] == "https://cdn.yupay.uz/broadcasts/pic.jpg"
    assert payload["caption"] == "<i>caption</i>"
    assert payload["parse_mode"] == "HTML"


@respx.mock
async def test_video_media_type_posts_send_video_and_captures_file_id() -> None:
    route = respx.post(f"{_BASE}/sendVideo").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "result": {"video": {"file_id": "VID123"}}}
        )
    )

    outcome = await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="caption text",
        media_type="video",
        media_url_or_file_id="https://cdn.yupay.uz/broadcasts/clip.mp4",
    )

    assert outcome.ok is True
    assert outcome.file_id == "VID123"
    payload = _json_body(route)
    assert payload["video"] == "https://cdn.yupay.uz/broadcasts/clip.mp4"
    assert payload["caption"] == "caption text"


@respx.mock
async def test_animation_media_type_posts_send_animation_and_captures_file_id() -> None:
    route = respx.post(f"{_BASE}/sendAnimation").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "result": {"animation": {"file_id": "GIF123"}}}
        )
    )

    outcome = await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="gif caption",
        media_type="animation",
        media_url_or_file_id="https://cdn.yupay.uz/broadcasts/anim.gif",
    )

    assert outcome.ok is True
    assert outcome.file_id == "GIF123"
    payload = _json_body(route)
    assert payload["animation"] == "https://cdn.yupay.uz/broadcasts/anim.gif"
    assert payload["caption"] == "gif caption"


@respx.mock
async def test_document_media_type_posts_send_document_and_captures_file_id() -> None:
    route = respx.post(f"{_BASE}/sendDocument").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "result": {"document": {"file_id": "DOC123"}}}
        )
    )

    outcome = await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="doc caption",
        media_type="document",
        media_url_or_file_id="https://cdn.yupay.uz/broadcasts/file.pdf",
    )

    assert outcome.ok is True
    assert outcome.file_id == "DOC123"
    payload = _json_body(route)
    assert payload["document"] == "https://cdn.yupay.uz/broadcasts/file.pdf"
    assert payload["caption"] == "doc caption"


@respx.mock
async def test_reused_file_id_is_sent_back_as_the_media_value() -> None:
    """Second+ sends pass Telegram's own file_id instead of the CDN URL."""
    route = respx.post(f"{_BASE}/sendPhoto").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {}})
    )

    await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="caption",
        media_type="photo",
        media_url_or_file_id="AgACAgEAAxkBAA...",
    )

    payload = _json_body(route)
    assert payload["photo"] == "AgACAgEAAxkBAA..."


@respx.mock
async def test_malformed_result_shape_is_still_a_successful_send() -> None:
    """A 200 whose result doesn't have the expected media key is still ``ok``."""
    respx.post(f"{_BASE}/sendPhoto").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {}})
    )

    outcome = await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="caption",
        media_type="photo",
        media_url_or_file_id="https://cdn.yupay.uz/broadcasts/pic.jpg",
    )

    assert outcome.ok is True
    assert outcome.file_id is None


@respx.mock
async def test_malformed_result_shape_is_still_ok_for_non_photo_media() -> None:
    """Same ambiguity-resolution rule applies to video/animation/document."""
    respx.post(f"{_BASE}/sendVideo").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {}})
    )

    outcome = await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="caption",
        media_type="video",
        media_url_or_file_id="https://cdn.yupay.uz/broadcasts/clip.mp4",
    )

    assert outcome.ok is True
    assert outcome.file_id is None


@respx.mock
async def test_403_blocked_is_not_ok_and_status_is_captured() -> None:
    respx.post(f"{_BASE}/sendMessage").mock(
        return_value=httpx.Response(
            403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"}
        )
    )

    outcome = await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="hi",
        media_type="none",
        media_url_or_file_id=None,
    )

    assert outcome.ok is False
    assert outcome.status == 403
    assert outcome.file_id is None
    assert outcome.retry_after is None
    assert "blocked" in outcome.description


@respx.mock
async def test_429_captures_retry_after() -> None:
    respx.post(f"{_BASE}/sendMessage").mock(
        return_value=httpx.Response(
            429,
            json={
                "ok": False,
                "description": "Too Many Requests: retry after 7",
                "parameters": {"retry_after": 7},
            },
        )
    )

    outcome = await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="hi",
        media_type="none",
        media_url_or_file_id=None,
    )

    assert outcome.ok is False
    assert outcome.status == 429
    assert outcome.retry_after == 7


@respx.mock
async def test_400_cant_parse_entities_is_not_ok() -> None:
    respx.post(f"{_BASE}/sendMessage").mock(
        return_value=httpx.Response(
            400,
            json={
                "ok": False,
                "description": "Bad Request: can't parse entities: unsupported tag",
            },
        )
    )

    outcome = await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="<blink>hi</blink>",
        media_type="none",
        media_url_or_file_id=None,
    )

    assert outcome.ok is False
    assert outcome.status == 400
    assert outcome.retry_after is None
    assert "can't parse entities" in outcome.description


@respx.mock
async def test_network_error_never_raises() -> None:
    respx.post(f"{_BASE}/sendMessage").mock(side_effect=httpx.ConnectError("boom"))

    outcome = await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="hi",
        media_type="none",
        media_url_or_file_id=None,
    )

    assert outcome.ok is False
    assert outcome.status == 0
    assert outcome.file_id is None
    assert outcome.description != ""


@respx.mock
async def test_description_is_truncated_to_roughly_200_chars() -> None:
    long_description = "Bad Request: " + ("x" * 500)
    respx.post(f"{_BASE}/sendMessage").mock(
        return_value=httpx.Response(400, json={"ok": False, "description": long_description})
    )

    outcome = await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="hi",
        media_type="none",
        media_url_or_file_id=None,
    )

    assert outcome.ok is False
    assert len(outcome.description) <= 200


@respx.mock
async def test_unknown_media_type_is_rejected_without_a_network_call() -> None:
    route = respx.post(url__regex=r".*").mock(return_value=httpx.Response(200))

    outcome = await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="hi",
        media_type="sticker",
        media_url_or_file_id=None,
    )

    assert outcome.ok is False
    assert outcome.status == 0
    assert not route.called


@respx.mock
async def test_non_json_error_body_does_not_raise() -> None:
    respx.post(f"{_BASE}/sendMessage").mock(
        return_value=httpx.Response(502, text="<html>Bad Gateway</html>")
    )

    outcome = await send_broadcast_message(
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        body_html="hi",
        media_type="none",
        media_url_or_file_id=None,
    )

    assert outcome.ok is False
    assert outcome.status == 502
    assert outcome.description == ""
    assert outcome.retry_after is None


def _json_body(route: respx.Route) -> dict[str, object]:
    """Decode the JSON body of the last request matched by ``route``."""
    result: dict[str, object] = json.loads(route.calls.last.request.read())
    return result
