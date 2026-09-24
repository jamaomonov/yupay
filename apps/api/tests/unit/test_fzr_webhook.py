"""The FazerCards webhook receiver.

Two things are worth pinning here and the rest follows from them.

**The signature is checked before the body is read.** §9 of AGENTS.md says so,
and the reason is concrete: an attacker who can post JSON at this endpoint can
otherwise make us reconcile a task of their choosing at a time of their
choosing. The test that matters is not "a good signature passes" — it is that a
forged one is refused even when the JSON inside it is perfectly well formed.

**Everything we cannot act on still answers 200.** FazerCards retries a
non-2xx three times and then, after fifty consecutive failures, disables the
webhook and waits for a human to re-enable it in their panel. A 404 for an
order we never placed would be honest, and fifty orders later it would have
switched the feature off silently.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

# The package first, deliberately. ``webhooks.fzr`` imports ``api.v1.deps``,
# and importing that submodule executes ``api.v1.__init__``, which imports
# every webhook router back — so importing the handler module *first* meets a
# half-built package. The app never does (it builds ``api.v1`` up front), and
# the g2b receiver has the same shape; only a unit test can reach it.
import yupay.api.v1  # noqa: F401  -- import order matters, see above
from yupay.api.webhooks import fzr as mod
from yupay.modules.fulfillment import service as fulfillment_svc

SECRET = "whsec_test"


def _sign(raw: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _body(
    event: str = "order.status_changed",
    order_id: str = "ord-9001",
    *,
    age_seconds: float = 0,
) -> bytes:
    """One delivery, timestamped relative to now.

    A fixed timestamp would start failing the freshness guard the day after it
    was written, which is a test that breaks for the wrong reason.
    """
    at = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return json.dumps(
        {
            "event": event,
            "event_id": "8f3a2c9e-1b4d-4f7a-9e2c-5b6a8c1d2e3f",
            "timestamp": at.isoformat().replace("+00:00", "Z"),
            "data": {
                "order_id": order_id,
                "type": "giftcard",
                "status": "completed",
                "previous_status": "processing",
            },
        }
    ).encode()


# ---------- the signature, which is the whole security of this endpoint ----------


def test_a_body_signed_with_our_secret_is_accepted() -> None:
    raw = _body()
    assert mod._signature_ok(raw, _sign(raw), SECRET) is True


def test_a_forged_signature_is_refused_however_valid_the_json_is() -> None:
    """The attack this endpoint exists to refuse: well-formed JSON from
    somebody who does not hold the secret."""
    raw = _body()
    assert mod._signature_ok(raw, _sign(raw, "not-our-secret"), SECRET) is False


def test_a_body_altered_after_signing_is_refused() -> None:
    """The signature covers the raw bytes, so changing the order id in flight
    invalidates it — which is what stops a replay being re-pointed at another
    task."""
    signature = _sign(_body(order_id="ord-9001"))
    assert mod._signature_ok(_body(order_id="ord-9999"), signature, SECRET) is False


def test_an_unset_secret_accepts_nothing() -> None:
    """Fails closed. An unconfigured receiver that accepted everything would
    be worse than one that accepts nothing, because it would look like it was
    working."""
    raw = _body()
    assert mod._signature_ok(raw, _sign(raw), "") is False


def test_a_missing_signature_header_is_refused() -> None:
    assert mod._signature_ok(_body(), "", SECRET) is False


def test_a_non_ascii_signature_header_fails_closed_rather_than_raising() -> None:
    """``hmac.compare_digest`` raises TypeError on non-ASCII ``str`` operands,
    and this header is untrusted wire input. A 500 here would be a refusal
    that counts toward their auto-disable counter for the wrong reason."""
    assert mod._signature_ok(_body(), "sha256=Ωμέγα", SECRET) is False


def test_the_prefix_alone_is_not_enough() -> None:
    assert mod._signature_ok(_body(), "sha256=", SECRET) is False
    assert mod._signature_ok(_body(), "deadbeef", SECRET) is False


# ---------- which events this receiver acts on ----------


@pytest.mark.parametrize(
    "event",
    ["order.created", "manual_service.chat.message", "manual_service.chat.waiting_reply", ""],
    ids=["created", "chat message", "chat waiting", "empty"],
)
def test_only_a_status_change_is_actionable(event: str) -> None:
    """``order.created`` tells us nothing we do not already know — we created
    it — and the chat events belong to a product we do not sell here."""
    assert event not in mod._ACTIONABLE


def test_a_status_change_is_actionable() -> None:
    assert "order.status_changed" in mod._ACTIONABLE


# ---------- the handler, with the database and the saga stubbed ----------


class _Result:
    def __init__(self, row: Any) -> None:
        self._row = row
        self.rowcount = 1

    def scalar_one_or_none(self) -> Any:
        return self._row


class _Db:
    def __init__(self, row: Any = None, rowcount: int = 1) -> None:
        self._row = row
        self._rowcount = rowcount
        self.queried = False
        self.committed = False
        self.statements = 0

    async def execute(self, *_a: Any, **_kw: Any) -> Any:
        self.queried = True
        self.statements += 1
        # The first execute is the task lookup, the second the UPDATE that
        # marks it due; the fake answers both from one place.
        out = _Result(self._row)
        out.rowcount = self._rowcount
        return out

    async def commit(self) -> None:
        self.committed = True


class _Request:
    """Only what the handler reads, so the test cannot drift from the route."""

    def __init__(self, raw: bytes, *, content_length: int | None = None) -> None:
        self._raw = raw
        self.json_reads = 0
        declared = len(raw) if content_length is None else content_length
        self.headers = {"content-length": str(declared)}

    async def body(self) -> bytes:
        return self._raw

    async def json(self) -> Any:
        self.json_reads += 1
        return json.loads(self._raw)


@pytest.fixture
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(mod, "get_settings", lambda: SimpleNamespace(fzr_webhook_secret=SECRET))


@pytest.mark.asyncio
async def test_a_forged_delivery_never_reaches_the_json(
    _secret: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§9: verify before parsing. Pinned by counting reads of the body rather
    than by reading the code, so a refactor that reorders the two fails."""
    from fastapi import HTTPException

    raw = _body()
    req = _Request(raw)
    db = _Db()
    with pytest.raises(HTTPException) as exc:
        await mod.receive_fzr_webhook(
            req,  # type: ignore[arg-type]
            db,  # type: ignore[arg-type]
            signature=_sign(raw, "wrong"),
        )

    assert exc.value.status_code == 401
    assert req.json_reads == 0
    # And nothing was looked up, let alone reconciled.
    assert db.queried is False


@pytest.mark.asyncio
async def test_an_unknown_order_is_acknowledged_not_refused(_secret: None) -> None:
    """Their fifty-failure auto-disable is why this is a 200."""
    raw = _body(order_id="ord-does-not-exist")
    out = await mod.receive_fzr_webhook(
        _Request(raw),  # type: ignore[arg-type]
        _Db(None),  # type: ignore[arg-type]
        signature=_sign(raw),
    )

    assert out == {"status": "unknown_order"}


@pytest.mark.asyncio
async def test_an_event_we_do_not_act_on_is_acknowledged_without_a_lookup(
    _secret: None,
) -> None:
    raw = _body(event="order.created")
    db = _Db(None)
    out = await mod.receive_fzr_webhook(
        _Request(raw),  # type: ignore[arg-type]
        db,  # type: ignore[arg-type]
        signature=_sign(raw),
    )

    assert out == {"status": "ignored", "event": "order.created"}
    assert db.queried is False


@pytest.mark.asyncio
async def test_a_status_change_with_no_order_id_is_acknowledged(_secret: None) -> None:
    raw = json.dumps({"event": "order.status_changed", "data": {}}).encode()
    out = await mod.receive_fzr_webhook(
        _Request(raw),  # type: ignore[arg-type]
        _Db(None),  # type: ignore[arg-type]
        signature=_sign(raw),
    )

    assert out["status"] == "ignored"


@pytest.mark.asyncio
async def test_signed_but_unparseable_json_is_acknowledged(_secret: None) -> None:
    """A valid signature over something that is not JSON is their bug, not an
    attack — and answering non-2xx would spend one of their fifty."""
    raw = b"not json at all"
    out = await mod.receive_fzr_webhook(
        _Request(raw),  # type: ignore[arg-type]
        _Db(None),  # type: ignore[arg-type]
        signature=_sign(raw),
    )

    assert out["status"] == "ignored"


@pytest.mark.asyncio
async def test_a_known_order_is_marked_due_and_never_reconciled_inline(
    _secret: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The body says "completed". We neither believe it nor go and check.

    Checking means a 20-second upstream call while this handler holds a pool
    connection, and the pool is 10 + 10. The handler marks the task due and
    the sweep does the asking. Pinned by failing if anything calls the
    reconciler from here.
    """
    from types import SimpleNamespace

    async def _must_not_run(_db: Any, *, task_id: str) -> Any:
        raise AssertionError("the webhook must not reconcile inline")

    # Patched on the service module itself rather than through the
    # handler's re-export, which mypy rightly refuses to treat as public.
    monkeypatch.setattr(fulfillment_svc, "process_webhook_update", _must_not_run)
    seen: dict[str, Any] = {}

    async def _mark(_db: Any, *, task_id: str) -> bool:
        seen["task_id"] = task_id
        return True

    monkeypatch.setattr(fulfillment_svc, "mark_due_now", _mark)
    raw = _body()
    db = _Db(SimpleNamespace(id="task-7"))
    out = await mod.receive_fzr_webhook(
        _Request(raw),  # type: ignore[arg-type]
        db,  # type: ignore[arg-type]
        signature=_sign(raw),
    )

    assert seen["task_id"] == "task-7"
    assert out == {"status": "queued"}
    assert db.committed is True


async def test_a_task_that_already_finished_is_acknowledged_not_retried(
    _secret: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A race with the sweep, not an error: the sweep got there first."""
    from types import SimpleNamespace

    async def _mark(_db: Any, *, task_id: str) -> bool:
        return False

    monkeypatch.setattr(fulfillment_svc, "mark_due_now", _mark)
    raw = _body()
    out = await mod.receive_fzr_webhook(
        _Request(raw),  # type: ignore[arg-type]
        _Db(SimpleNamespace(id="task-7")),  # type: ignore[arg-type]
        signature=_sign(raw),
    )

    assert out == {"status": "already_final"}


# ---------- the two guards added after the security review ----------


@pytest.mark.asyncio
async def test_an_oversized_body_is_refused_before_it_is_read(_secret: None) -> None:
    """Content-Length is checked first, so the bytes are never pulled into
    memory. That is the whole cost being avoided."""
    from fastapi import HTTPException

    req = _Request(_body(), content_length=mod.MAX_BODY_BYTES + 1)
    with pytest.raises(HTTPException) as exc:
        await mod.receive_fzr_webhook(
            req,  # type: ignore[arg-type]
            _Db(None),  # type: ignore[arg-type]
            signature="sha256=whatever",
        )

    assert exc.value.status_code == 413
    assert req.json_reads == 0


@pytest.mark.asyncio
async def test_a_chunked_oversized_body_is_still_refused(_secret: None) -> None:
    """A chunked request declares no length, so the cap is enforced twice."""
    from fastapi import HTTPException

    big = b"x" * (mod.MAX_BODY_BYTES + 10)
    req = _Request(big, content_length=None)
    req.headers = {}
    with pytest.raises(HTTPException) as exc:
        await mod.receive_fzr_webhook(
            req,  # type: ignore[arg-type]
            _Db(None),  # type: ignore[arg-type]
            signature=_sign(big),
        )

    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_a_delivery_older_than_the_window_is_ignored(_secret: None) -> None:
    raw = _body(age_seconds=mod.MAX_AGE_SECONDS + 60)
    out = await mod.receive_fzr_webhook(
        _Request(raw),  # type: ignore[arg-type]
        _Db(None),  # type: ignore[arg-type]
        signature=_sign(raw),
    )

    assert out == {"status": "ignored", "reason": "stale"}


@pytest.mark.asyncio
async def test_their_slowest_legitimate_retry_still_gets_through(
    _secret: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Their ladder is 1, 5 and 30 minutes and a retry carries the ORIGINAL
    timestamp. A window under ~36 minutes would refuse their own third
    attempt — and non-2xx is what spends their fifty."""
    from types import SimpleNamespace

    async def _mark(_db: Any, *, task_id: str) -> bool:
        return True

    monkeypatch.setattr(fulfillment_svc, "mark_due_now", _mark)
    raw = _body(age_seconds=36 * 60)
    out = await mod.receive_fzr_webhook(
        _Request(raw),  # type: ignore[arg-type]
        _Db(SimpleNamespace(id="task-7")),  # type: ignore[arg-type]
        signature=_sign(raw),
    )

    assert out == {"status": "queued"}


def test_a_timestamp_we_cannot_read_is_not_treated_as_stale() -> None:
    """Refusing a real delivery over a field we only use for defence in depth
    would cost more than the field is worth."""
    assert mod._too_old({}) is False
    assert mod._too_old({"timestamp": ""}) is False
    assert mod._too_old({"timestamp": "not a date"}) is False
