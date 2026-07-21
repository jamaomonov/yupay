"""Unit tests for ``broadcasts`` schemas — pure Pydantic, no DB.

Focuses on the parts ``test_broadcasts_service.py`` never exercises directly, since it only
ever asserts on the ORM objects the service returns, not on the ``*Out`` DTOs built from them:
- ``RecipientOut.tg_chat_id`` must come out as a ``str`` even though the ORM column is a
  Postgres ``bigint`` (Python ``int``) — this is the money-rule-for-big-ids behavior, and it
  is load-bearing precisely because Pydantic v2's lax mode does *not* auto-coerce ``int`` to
  ``str``; without the ``mode="before"`` validator this would raise instead of stringifying.
- ``BroadcastOut`` round-trips a full ORM-shaped object via ``from_attributes``.
- ``BroadcastListOut`` / ``ScheduleIn`` / ``AudienceCountOut`` construct as plain DTOs.
- An invalid ``Literal`` value (e.g. ``media_type="gif"``, which isn't in the allowed five)
  is rejected with a Pydantic ``ValidationError`` rather than silently accepted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from yupay.modules.broadcasts.schemas import (
    AudienceCountOut,
    BroadcastCreateIn,
    BroadcastListOut,
    BroadcastOut,
    RecipientOut,
    ScheduleIn,
)


def _broadcast_row(**overrides: object) -> SimpleNamespace:
    """A ``Broadcast``-shaped object carrying every field ``BroadcastOut`` reads."""
    base: dict[str, object] = {
        "id": "b-1",
        "title": "Promo blast",
        "status": "draft",
        "body_html": "<b>Hello</b>",
        "media_type": "none",
        "media_url": None,
        "media_file_id": None,
        "locale_filter": "ru",
        "disable_web_page_preview": True,
        "scheduled_at": None,
        "total_recipients": 0,
        "sent_count": 0,
        "failed_count": 0,
        "blocked_count": 0,
        "started_at": None,
        "finished_at": None,
        "last_error": None,
        "created_by": "admin-1",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_recipient_out_stringifies_an_int_tg_chat_id() -> None:
    """The load-bearing case: a real bigint column value must come out as ``str``."""
    row = SimpleNamespace(
        user_id="u1",
        tg_chat_id=123456789012,
        status="sent",
        error=None,
        sent_at=None,
    )
    out = RecipientOut.model_validate(row)
    assert out.tg_chat_id == "123456789012"
    assert isinstance(out.tg_chat_id, str)


def test_recipient_out_accepts_all_statuses() -> None:
    for status in ("pending", "sent", "failed", "blocked"):
        row = SimpleNamespace(user_id="u1", tg_chat_id=1, status=status, error=None, sent_at=None)
        assert RecipientOut.model_validate(row).status == status


def test_recipient_out_rejects_invalid_status() -> None:
    row = SimpleNamespace(user_id="u1", tg_chat_id=1, status="bogus", error=None, sent_at=None)
    with pytest.raises(ValidationError):
        RecipientOut.model_validate(row)


def test_broadcast_out_round_trips_from_orm_shaped_object() -> None:
    row = _broadcast_row(
        status="scheduled",
        media_type="photo",
        media_url="https://cdn.example.com/x.jpg",
        media_file_id="AgAC...",
        locale_filter="uz",
        scheduled_at=datetime.now(UTC),
        total_recipients=100,
        sent_count=10,
        failed_count=1,
        blocked_count=2,
    )
    out = BroadcastOut.model_validate(row)
    assert out.id == "b-1"
    assert out.status == "scheduled"
    assert out.media_type == "photo"
    assert out.locale_filter == "uz"
    assert out.total_recipients == 100
    assert out.sent_count == 10
    assert out.failed_count == 1
    assert out.blocked_count == 2
    assert out.media_url == "https://cdn.example.com/x.jpg"
    assert out.media_file_id == "AgAC..."


def test_broadcast_out_accepts_locale_filter_none() -> None:
    out = BroadcastOut.model_validate(_broadcast_row(locale_filter=None))
    assert out.locale_filter is None


def test_broadcast_out_rejects_invalid_status_literal() -> None:
    with pytest.raises(ValidationError):
        BroadcastOut.model_validate(_broadcast_row(status="not-a-real-status"))


def test_broadcast_list_out_preserves_total() -> None:
    items = [
        BroadcastOut.model_validate(_broadcast_row(id="b-1")),
        BroadcastOut.model_validate(_broadcast_row(id="b-2")),
    ]
    listed = BroadcastListOut(items=items, total=5)
    assert listed.total == 5
    assert [i.id for i in listed.items] == ["b-1", "b-2"]


def test_schedule_in_parses_aware_datetime() -> None:
    when = datetime.now(UTC)
    parsed = ScheduleIn(scheduled_at=when)
    assert parsed.scheduled_at == when


def test_audience_count_out_preserves_count() -> None:
    assert AudienceCountOut(count=42).count == 42


def test_broadcast_create_in_rejects_invalid_media_type() -> None:
    """``"gif"`` isn't one of the five allowed ``media_type`` values (``animation`` is)."""
    with pytest.raises(ValidationError):
        BroadcastCreateIn(title="x", media_type="gif")  # type: ignore[arg-type]


def test_broadcast_create_in_rejects_invalid_locale_filter() -> None:
    with pytest.raises(ValidationError):
        BroadcastCreateIn(title="x", locale_filter="fr")  # type: ignore[arg-type]


def test_broadcast_create_in_defaults() -> None:
    created = BroadcastCreateIn(title="x")
    assert created.body_html == ""
    assert created.media_type == "none"
    assert created.media_url is None
    assert created.locale_filter is None
    assert created.disable_web_page_preview is True
