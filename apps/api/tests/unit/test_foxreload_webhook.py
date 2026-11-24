"""The FoxReload webhook receiver (ADR-0107).

Pinned: the signature (HMAC over ``"{t}." + raw body``, their documented
scheme) is checked before the body is read, a stale timestamp is refused, and
everything we cannot act on still answers 200 — they retry a non-2xx five times
for nothing. A known order is only marked due; the sweep does the reading.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from typing import Any

import pytest
import yupay.api.v1  # noqa: F401  -- import order matters, see test_fzr_webhook
from yupay.api.webhooks import foxreload as mod
from yupay.modules.fulfillment import service as fulfillment_svc

SECRET = "whsec_fox"
ORDER_ID = "0190f0f0-0000-7000-8000-000000000001"


def _sign(raw: bytes, *, secret: str = SECRET, at: int | None = None) -> str:
    stamp = int(time.time()) if at is None else at
    digest = hmac.new(secret.encode(), f"{stamp}.".encode() + raw, hashlib.sha256).hexdigest()
    return f"t={stamp},v1={digest}"


def _body(event: str = "order.completed", order_id: str = ORDER_ID) -> bytes:
    return json.dumps(
        {
            "id": "evt-1",
            "type": event,
            "createdAt": "2026-11-24T12:00:00Z",
            "data": {"id": order_id},
        }
    ).encode()


# ---------- the signature ----------


def test_their_documented_signature_is_accepted() -> None:
    raw = _body()
    assert mod._signature_ok(raw, _sign(raw), SECRET) is True


def test_a_forged_signature_is_refused() -> None:
    raw = _body()
    assert mod._signature_ok(raw, _sign(raw, secret="nope"), SECRET) is False


def test_a_body_changed_after_signing_is_refused() -> None:
    header = _sign(_body(order_id="a"))
    assert mod._signature_ok(_body(order_id="b"), header, SECRET) is False


def test_a_stale_or_future_timestamp_is_refused() -> None:
    raw = _body()
    old = int(time.time()) - 301
    assert mod._signature_ok(raw, _sign(raw, at=old), SECRET) is False
    assert mod._signature_ok(raw, _sign(raw, at=int(time.time()) + 301), SECRET) is False


@pytest.mark.parametrize("header", ["", "v1=abc", "t=x,v1=abc", "t=1", "garbage", "t=1,v1=Ωμέγα"])
def test_a_malformed_header_fails_closed(header: str) -> None:
    assert mod._signature_ok(_body(), header, SECRET) is False


def test_an_unset_secret_accepts_nothing() -> None:
    raw = _body()
    assert mod._signature_ok(raw, _sign(raw), "") is False


# ---------- the handler ----------


class _Result:
    def __init__(self, row: Any) -> None:
        self._row = row

    def scalar_one_or_none(self) -> Any:
        return self._row


class _Db:
    def __init__(self, row: Any = None) -> None:
        self._row = row
        self.queried = False
        self.committed = False

    async def execute(self, *_a: Any, **_kw: Any) -> Any:
        self.queried = True
        return _Result(self._row)

    async def commit(self) -> None:
        self.committed = True


class _Request:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw
        self.json_reads = 0
        self.headers = {"content-length": str(len(raw))}

    async def body(self) -> bytes:
        return self._raw

    async def json(self) -> Any:
        self.json_reads += 1
        return json.loads(self._raw)


@pytest.fixture
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mod, "get_settings", lambda: SimpleNamespace(foxreload_webhook_secret=SECRET)
    )


async def test_a_forged_delivery_never_reaches_the_json(_secret: None) -> None:
    from fastapi import HTTPException

    raw = _body()
    req, db = _Request(raw), _Db()
    with pytest.raises(HTTPException) as exc:
        await mod.receive_foxreload_webhook(req, db, signature=_sign(raw, secret="x"))  # type: ignore[arg-type]
    assert exc.value.status_code == 401
    assert req.json_reads == 0
    assert db.queried is False


async def test_a_known_order_is_marked_due_not_reconciled_inline(
    _secret: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _must_not_run(_db: Any, *, task_id: str) -> Any:
        raise AssertionError("the webhook must not reconcile inline")

    seen: dict[str, str] = {}

    async def _mark(_db: Any, *, task_id: str) -> bool:
        seen["task_id"] = task_id
        return True

    monkeypatch.setattr(fulfillment_svc, "process_webhook_update", _must_not_run)
    monkeypatch.setattr(fulfillment_svc, "mark_due_now", _mark)
    raw = _body()
    db = _Db(SimpleNamespace(id="task-7"))
    out = await mod.receive_foxreload_webhook(_Request(raw), db, signature=_sign(raw))  # type: ignore[arg-type]

    assert out == {"status": "queued"}
    assert seen["task_id"] == "task-7"
    assert db.committed is True


async def test_an_unknown_order_is_acknowledged(_secret: None) -> None:
    raw = _body()
    out = await mod.receive_foxreload_webhook(_Request(raw), _Db(None), signature=_sign(raw))  # type: ignore[arg-type]
    assert out == {"status": "unknown_order"}


@pytest.mark.parametrize("event", ["topup.credited", "banking_card.three_ds_code", ""])
async def test_other_events_are_acknowledged_without_a_lookup(_secret: None, event: str) -> None:
    raw = _body(event=event)
    db = _Db(None)
    out = await mod.receive_foxreload_webhook(_Request(raw), db, signature=_sign(raw))  # type: ignore[arg-type]
    assert out["status"] == "ignored"
    assert db.queried is False


async def test_signed_but_not_json_is_acknowledged(_secret: None) -> None:
    raw = b"not json"
    out = await mod.receive_foxreload_webhook(_Request(raw), _Db(None), signature=_sign(raw))  # type: ignore[arg-type]
    assert out["status"] == "ignored"
