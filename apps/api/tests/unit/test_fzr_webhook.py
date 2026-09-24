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


def _body(event: str = "order.status_changed", order_id: str = "ord-9001") -> bytes:
    return json.dumps(
        {
            "event": event,
            "event_id": "8f3a2c9e-1b4d-4f7a-9e2c-5b6a8c1d2e3f",
            "timestamp": "2026-09-24T12:34:56.789Z",
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

    def scalar_one_or_none(self) -> Any:
        return self._row


class _Db:
    def __init__(self, row: Any = None) -> None:
        self._row = row
        self.queried = False

    async def execute(self, *_a: Any, **_kw: Any) -> Any:
        self.queried = True
        return _Result(self._row)


class _Request:
    """Only what the handler reads, so the test cannot drift from the route."""

    def __init__(self, raw: bytes) -> None:
        self._raw = raw
        self.json_reads = 0

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
async def test_a_known_order_is_reconciled_through_the_adapter_not_the_body(
    _secret: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The body says "completed". We do not believe it: the task is handed to
    ``process_webhook_update``, which asks the adapter's own check_status."""
    from types import SimpleNamespace

    seen: dict[str, Any] = {}

    async def _process(_db: Any, *, task_id: str) -> Any:
        seen["task_id"] = task_id
        return SimpleNamespace(id=task_id, status="delivered")

    # Patched on the service module itself rather than through the
    # handler's re-export, which mypy rightly refuses to treat as public.
    monkeypatch.setattr(fulfillment_svc, "process_webhook_update", _process)
    raw = _body()
    out = await mod.receive_fzr_webhook(
        _Request(raw),  # type: ignore[arg-type]
        _Db(SimpleNamespace(id="task-7")),  # type: ignore[arg-type]
        signature=_sign(raw),
    )

    assert seen["task_id"] == "task-7"
    assert out == {"status": "processed", "task_status": "delivered"}
