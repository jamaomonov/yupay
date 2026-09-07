"""Draining the merchant webhook outbox (M3a, Task 4).

The consumer half of §10. Task 3 writes ``merchant_webhook_deliveries`` rows in
the transaction that causes them; this drain claims them with ``FOR UPDATE SKIP
LOCKED``, signs each one, POSTs it through the SSRF-hardened client, and writes
the answer back onto the row — which is also M4's cabinet delivery log, so the
writing is the feature, not the bookkeeping.

Most tests stub the transport at ``webhook_delivery.post_json`` and drive the
**decision table** against a real database: the transport itself is proven
against real sockets in ``test_outbound_ssrf_live.py``, and what is untested
without a DB is the part that writes rows, counts a streak and disables a hook.
Two tests deliberately use the **real** client — the policy refusal and its
delivery log — because "a blocked address is recorded as a refusal, not as a
network error" is a claim about the two modules being wired together, and a
stub that raises the right class proves nothing about that.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import yupay.api.v1  # noqa: F401  isort: skip  -- break the import cycle
from yupay.core import crypto
from yupay.core.config import get_settings
from yupay.core.ids import new_id
from yupay.core.outbound import OutboundResponse, post_json
from yupay.core.outbound_errors import (
    ConnectFailedError,
    ContentEncodingNotAllowedError,
    OutboundBrokenError,
    OutboundTimeoutError,
    ResponseTooLargeError,
)
from yupay.modules.merchants import admin as merchants_admin
from yupay.modules.merchants import webhook_delivery, webhook_outcome, webhook_retry
from yupay.modules.merchants import webhooks as hooks
from yupay.modules.merchants.models import (
    WEBHOOK_LAST_ERROR_MAX,
    WEBHOOK_RESPONSE_BODY_MAX,
    MerchantUser,
    MerchantWebhook,
    MerchantWebhookDelivery,
)
from yupay.modules.merchants.service import create_merchant

pytestmark = pytest.mark.asyncio

HOOK_URL = "https://hooks.reseller.example/yupay"
OPERATOR_EMAIL = "ops@reseller.example"


# ---------- harness ----------


async def _merchant_with_hook(
    db: AsyncSession, *, url: str = HOOK_URL, email: str | None = OPERATOR_EMAIL
) -> tuple[str, str]:
    """A merchant, a cabinet operator to email, and a configured webhook.

    Returns:
        ``(merchant_id, secret)`` — the plaintext secret the row holds
        encrypted, so a test can recompute the signature we are supposed to
        have sent.
    """
    merchant = await create_merchant(db, title=f"Reseller {new_id()[:8]}")
    if email is not None:
        db.add(
            MerchantUser(
                id=new_id(),
                merchant_id=merchant.id,
                email=f"{new_id().replace('-', '')}.{email}",
                password_hash="x",
            )
        )
    configured = await merchants_admin.set_webhook(db, merchant_id=merchant.id, url=url)
    assert configured.secret is not None
    await db.commit()
    return merchant.id, configured.secret


def _enqueue(
    db: AsyncSession,
    merchant_id: str,
    *,
    event_type: str = hooks.EVENT_ORDER_STATUS_CHANGED,
    payload: dict[str, Any] | None = None,
    url: str = HOOK_URL,
    next_attempt_at: datetime | None = None,
    delivery_id: str | None = None,
) -> str:
    """Add one pending delivery row the way Task 3's producer does.

    Inserted directly rather than through ``webhooks.enqueue`` so a test can
    place a row at a chosen ``next_attempt_at``; the producer itself is covered
    in ``test_merchant_webhook_events.py``.
    """
    delivery_id = delivery_id or new_id()
    row = MerchantWebhookDelivery(
        id=delivery_id,
        merchant_id=merchant_id,
        url=url,
        event_type=event_type,
        payload=payload or {"merchant_order_id": "o-1", "order_id": new_id(), "status": "paid"},
    )
    if next_attempt_at is not None:
        row.next_attempt_at = next_attempt_at
    db.add(row)
    return delivery_id


async def _row(db: AsyncSession, delivery_id: str) -> MerchantWebhookDelivery:
    await db.commit()  # see the delivery's own committed state, not a cached one
    row = await db.get(MerchantWebhookDelivery, delivery_id)
    assert row is not None
    await db.refresh(row)
    return row


async def _hook(db: AsyncSession, merchant_id: str) -> MerchantWebhook:
    hook = (
        await db.execute(select(MerchantWebhook).where(MerchantWebhook.merchant_id == merchant_id))
    ).scalar_one()
    await db.refresh(hook)
    return hook


class _Sender:
    """Stands in for ``core.outbound.post_json``, recording every attempt.

    ``answers`` is consumed one per call, the last repeating; an
    ``OutboundError`` in the list is raised rather than returned, which is how
    the failure half of the table is driven.
    """

    def __init__(self, *answers: OutboundResponse | BaseException) -> None:
        self._answers: list[OutboundResponse | BaseException] = list(answers)
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        url: str,
        *,
        body: bytes,
        headers: Mapping[str, str] | None = None,
        timeout: float = 10.0,
        max_bytes: int = 65536,
    ) -> OutboundResponse:
        self.calls.append({"url": url, "body": body, "headers": dict(headers or {})})
        answer = self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _ok(status: int = 200, body: str = "ok", retry_after: str | None = None) -> OutboundResponse:
    return OutboundResponse(
        status_code=status,
        body=body,
        address="93.184.216.34",
        elapsed_ms=12,
        retry_after=retry_after,
    )


def _install(monkeypatch: pytest.MonkeyPatch, sender: _Sender) -> _Sender:
    monkeypatch.setattr(webhook_delivery, "post_json", sender)
    return sender


def _spy_email(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    sent: list[dict[str, str]] = []

    async def _send(*, to: str, subject: str, html: str, text: str) -> str:
        sent.append({"to": to, "subject": subject, "text": text})
        return "msg_test"

    monkeypatch.setattr(webhook_outcome, "send_email", _send)
    return sent


async def _settle_sends() -> None:
    """Let the fire-and-forget after-commit sends actually run."""
    for _ in range(10):
        await asyncio.sleep(0.01)


# ---------- the happy path, and what it signs ----------


async def test_a_200_marks_the_row_delivered_and_logs_their_answer(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    merchant_id, _ = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id)
    await db_session.commit()
    sender = _install(monkeypatch, _Sender(_ok(200, "thanks")))

    assert await webhook_delivery.drain_pending_deliveries(db_session) == 1

    row = await _row(db_session, delivery_id)
    assert row.status == "delivered"
    assert row.attempts_count == 1
    assert row.response_code == 200
    assert row.response_body == "thanks"
    assert row.last_error is None
    assert len(sender.calls) == 1
    assert sender.calls[0]["url"] == HOOK_URL


async def test_a_delivery_is_signed_with_the_documented_canonical_string(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recipe a third party implements verification from, recomputed here
    from the prose rather than from our own helper — if the two ever disagree,
    every integrator's verifier breaks and this is the test that says so."""
    merchant_id, secret = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id)
    await db_session.commit()
    sender = _install(monkeypatch, _Sender(_ok()))

    await webhook_delivery.drain_pending_deliveries(db_session)

    call = sender.calls[0]
    headers = call["headers"]
    assert headers["X-Yupay-Delivery"] == delivery_id
    assert headers["X-Yupay-Event"] == hooks.EVENT_ORDER_STATUS_CHANGED
    assert headers["X-Yupay-Timestamp"].isdigit()
    message = "\n".join(
        (
            headers["X-Yupay-Timestamp"],
            delivery_id,
            hooks.EVENT_ORDER_STATUS_CHANGED,
            hashlib.sha256(call["body"]).hexdigest(),
        )
    ).encode()
    assert (
        headers["X-Yupay-Signature"]
        == hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    )
    # The body is exactly the stored payload, so the merchant can hash what
    # they parse.
    row = await _row(db_session, delivery_id)
    assert json.loads(call["body"]) == row.payload


async def test_the_signature_is_keyed_by_the_secret_decrypted_at_send_time(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row holds ciphertext; nothing but this send path may hold the key
    material, and it must come out under the webhook purpose label."""
    merchant_id, secret = await _merchant_with_hook(db_session)
    _enqueue(db_session, merchant_id)
    await db_session.commit()
    hook = await _hook(db_session, merchant_id)
    assert secret.encode() not in hook.secret_enc
    assert (
        crypto.decrypt(hook.secret_enc, hook.secret_nonce, purpose=crypto.PURPOSE_MERCHANT_WEBHOOK)
        == secret
    )

    sender = _install(monkeypatch, _Sender(_ok()))
    await webhook_delivery.drain_pending_deliveries(db_session)

    # And it never travels in the body or in a header of its own.
    call = sender.calls[0]
    assert secret.encode() not in call["body"]
    assert not any(secret in value for value in call["headers"].values())


async def test_a_success_resets_the_streak_and_stamps_the_hook(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    merchant_id, _ = await _merchant_with_hook(db_session)
    hook = await _hook(db_session, merchant_id)
    hook.failure_streak = 5
    _enqueue(db_session, merchant_id)
    await db_session.commit()
    _install(monkeypatch, _Sender(_ok()))

    await webhook_delivery.drain_pending_deliveries(db_session)

    hook = await _hook(db_session, merchant_id)
    assert hook.failure_streak == 0
    assert hook.last_success_at is not None
    assert hook.disabled_at is None


# ---------- retry, terminal, and the schedule ----------


async def test_a_500_stays_pending_and_comes_back_later(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    merchant_id, _ = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id)
    await db_session.commit()
    before = datetime.now(UTC)
    _install(monkeypatch, _Sender(_ok(500, "boom")))

    await webhook_delivery.drain_pending_deliveries(db_session)

    row = await _row(db_session, delivery_id)
    assert row.status == "pending"
    assert row.attempts_count == 1
    assert row.response_code == 500
    assert row.response_body == "boom"
    assert row.last_error is not None
    assert row.next_attempt_at > before + timedelta(seconds=webhook_retry.BACKOFF_BASE_SECONDS - 5)
    hook = await _hook(db_session, merchant_id)
    assert hook.failure_streak == 1
    assert hook.last_failure_at is not None


async def test_a_row_whose_backoff_has_not_elapsed_is_not_claimed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The claim predicate, and the reason ``next_attempt_at`` is NOT NULL."""
    merchant_id, _ = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(
        db_session, merchant_id, next_attempt_at=datetime.now(UTC) + timedelta(minutes=5)
    )
    await db_session.commit()
    sender = _install(monkeypatch, _Sender(_ok()))

    assert await webhook_delivery.drain_pending_deliveries(db_session) == 0

    assert sender.calls == []
    assert (await _row(db_session, delivery_id)).status == "pending"


async def test_a_404_is_terminal(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Their endpoint rejected the delivery. A retry sends the same body to the
    same URL and gets the same answer, so the row is done."""
    merchant_id, _ = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id)
    await db_session.commit()
    _install(monkeypatch, _Sender(_ok(404, "no such route")))

    await webhook_delivery.drain_pending_deliveries(db_session)
    row = await _row(db_session, delivery_id)
    assert row.status == "failed"
    assert row.response_code == 404

    # And the drain never picks it up again.
    assert await webhook_delivery.drain_pending_deliveries(db_session) == 0
    assert (await _row(db_session, delivery_id)).attempts_count == 1


async def test_a_429_honours_their_retry_after(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    merchant_id, _ = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id)
    await db_session.commit()
    before = datetime.now(UTC)
    _install(monkeypatch, _Sender(_ok(429, "slow down", retry_after="90")))

    await webhook_delivery.drain_pending_deliveries(db_session)

    row = await _row(db_session, delivery_id)
    assert row.status == "pending"
    delay = (row.next_attempt_at - before).total_seconds()
    # 90 s as asked, and NOT the 30 s the backoff would have chosen.
    assert 80 < delay < 100


async def test_a_received_refusal_is_terminal_because_a_retry_would_re_deliver(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ResponseTooLargeError`` / ``ContentEncodingNotAllowedError`` are our
    refusals of their *answer* — their server already has the webhook."""
    for error in (ResponseTooLargeError("too big"), ContentEncodingNotAllowedError("gzip")):
        merchant_id, _ = await _merchant_with_hook(db_session)
        delivery_id = _enqueue(db_session, merchant_id)
        await db_session.commit()
        _install(monkeypatch, _Sender(error))

        await webhook_delivery.drain_pending_deliveries(db_session)

        row = await _row(db_session, delivery_id)
        assert row.status == "failed", type(error).__name__
        assert row.response_code is None
        assert type(error).__name__ in (row.last_error or "")


async def test_a_transport_failure_retries_and_records_the_type_not_a_status(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    merchant_id, _ = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id)
    await db_session.commit()
    _install(monkeypatch, _Sender(ConnectFailedError("host could not be reached")))

    await webhook_delivery.drain_pending_deliveries(db_session)

    row = await _row(db_session, delivery_id)
    assert row.status == "pending"
    assert row.response_code is None
    assert "ConnectFailedError" in (row.last_error or "")


async def test_a_row_is_given_up_on_at_the_attempt_ceiling(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    merchant_id, _ = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id)
    await db_session.commit()
    row = await _row(db_session, delivery_id)
    row.attempts_count = webhook_retry.MAX_ATTEMPTS - 1
    await db_session.commit()
    _install(monkeypatch, _Sender(OutboundTimeoutError("no answer")))

    await webhook_delivery.drain_pending_deliveries(db_session)

    row = await _row(db_session, delivery_id)
    assert row.attempts_count == webhook_retry.MAX_ATTEMPTS
    assert row.status == "failed"


# ---------- our own bug is never the merchant's fault ----------


async def test_our_own_broken_attempt_never_touches_the_failure_streak(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``OutboundBrokenError`` means the attempt broke in a way neither side
    chose. Counting it would auto-disable a working endpoint and tell the
    merchant, in the log they read, that we refused their URL."""
    merchant_id, _ = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id)
    await db_session.commit()
    _install(monkeypatch, _Sender(OutboundBrokenError("the attempt broke: TypeError")))

    await webhook_delivery.drain_pending_deliveries(db_session)

    assert (await _row(db_session, delivery_id)).status == "failed"
    hook = await _hook(db_session, merchant_id)
    assert hook.failure_streak == 0
    assert hook.last_failure_at is None
    assert hook.disabled_at is None


async def test_a_poisoned_row_is_failed_and_the_rest_of_the_batch_still_lands(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-row SAVEPOINT, exercised with the failure the module docstring
    names: a bug in *our* recording code.

    ``post_json`` is total, so no transport failure reaches this belt — what
    does is a write that trips a column bound, and the truncation is removed
    here to produce exactly that. A ``DataError`` **poisons the session** until
    something rolls back, so without the savepoint the next row's flush raises
    ``PendingRollbackError``, the whole batch is discarded, and the poisoned row
    is left ``pending`` for the next tick to crash on again. (A plain
    ``RuntimeError`` from the sender does *not* poison the session, and a test
    built on one stays green with the savepoint deleted — checked.)
    """
    merchant_id, _ = await _merchant_with_hook(db_session)
    first = _enqueue(db_session, merchant_id)
    poisoned = _enqueue(db_session, merchant_id)
    third = _enqueue(db_session, merchant_id)
    await db_session.commit()

    monkeypatch.setattr(webhook_outcome, "_clip", lambda text, limit: text)

    class _Poison(_Sender):
        async def __call__(self, url: str, **kwargs: Any) -> OutboundResponse:
            headers = kwargs.get("headers") or {}
            await super().__call__(url, **kwargs)
            if headers.get("X-Yupay-Delivery") == poisoned:
                return _ok(500, "y" * (WEBHOOK_RESPONSE_BODY_MAX * 50))
            return _ok()

    _install(monkeypatch, _Poison(_ok()))

    assert await webhook_delivery.drain_pending_deliveries(db_session) == 3

    assert (await _row(db_session, first)).status == "delivered"
    assert (await _row(db_session, third)).status == "delivered"
    dead = await _row(db_session, poisoned)
    assert dead.status == "failed"
    # SQLAlchemy surfaces the truncation as ``DataError``, or as ``DBAPIError``
    # when it is raised out of a query-invoked autoflush (which is where it
    # lands here — the over-long value is flushed by the hook-row SELECT).
    assert (dead.last_error or "").startswith(("DataError", "DBAPIError"))


# ---------- the auto-disable ----------


async def test_a_sustained_failure_streak_disables_the_hook_and_emails_once(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MERCHANT_WEBHOOK_DISABLE_AFTER_FAILURES", "3")
    get_settings.cache_clear()
    try:
        merchant_id, _ = await _merchant_with_hook(db_session)
        for _ in range(5):
            _enqueue(db_session, merchant_id)
        await db_session.commit()
        sent = _spy_email(monkeypatch)
        sender = _install(monkeypatch, _Sender(_ok(500, "boom")))

        await webhook_delivery.drain_pending_deliveries(db_session)
        await db_session.commit()
        await _settle_sends()

        hook = await _hook(db_session, merchant_id)
        assert hook.disabled_at is not None
        # Exactly the threshold: rows 4 and 5 were claimed while the hook was
        # still on, and are skipped once it goes off rather than delivered to
        # an endpoint we have just switched off.
        assert hook.failure_streak == 3
        assert len(sender.calls) == 3
        assert len(sent) == 1, "exactly one email per disable, not one per failed attempt"
        assert sent[0]["to"].endswith(OPERATOR_EMAIL)
        assert "hooks.reseller.example" in sent[0]["text"]
        assert "3" in sent[0]["text"]

        # The skipped rows are untouched, and re-enabling delivers them.
        skipped = [
            row
            for row in (
                await db_session.execute(
                    select(MerchantWebhookDelivery).where(
                        MerchantWebhookDelivery.merchant_id == merchant_id
                    )
                )
            ).scalars()
            if row.attempts_count == 0
        ]
        assert len(skipped) == 2
        assert {row.status for row in skipped} == {"pending"}
    finally:
        get_settings.cache_clear()


async def test_a_disabled_hook_stops_the_drain_and_re_enabling_resumes_it(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disabling is not a delete, and the queued rows are not thrown away:
    ``PUT /admin/merchants/{id}/webhook`` clears ``disabled_at`` and the streak,
    and that IS the recovery path (Task 1) — the backlog picks up from there."""
    merchant_id, _ = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id)
    await merchants_admin.disable_webhook(db_session, merchant_id=merchant_id)
    await db_session.commit()
    sender = _install(monkeypatch, _Sender(_ok()))

    assert await webhook_delivery.drain_pending_deliveries(db_session) == 0
    assert sender.calls == []
    assert (await _row(db_session, delivery_id)).status == "pending"

    await merchants_admin.set_webhook(db_session, merchant_id=merchant_id, url=HOOK_URL)
    await db_session.commit()

    assert await webhook_delivery.drain_pending_deliveries(db_session) == 1
    assert (await _row(db_session, delivery_id)).status == "delivered"


async def test_a_merchant_with_no_operator_is_disabled_without_an_email(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The disable must happen whether or not there is anyone to tell — a
    send that cannot find a recipient is not a reason to keep hammering."""
    monkeypatch.setenv("MERCHANT_WEBHOOK_DISABLE_AFTER_FAILURES", "1")
    get_settings.cache_clear()
    try:
        merchant_id, _ = await _merchant_with_hook(db_session, email=None)
        _enqueue(db_session, merchant_id)
        await db_session.commit()
        sent = _spy_email(monkeypatch)
        _install(monkeypatch, _Sender(_ok(500, "boom")))

        await webhook_delivery.drain_pending_deliveries(db_session)
        await db_session.commit()
        await _settle_sends()

        assert (await _hook(db_session, merchant_id)).disabled_at is not None
        assert sent == []
    finally:
        get_settings.cache_clear()


async def test_an_unknown_event_type_is_refused_rather_than_signed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing can put one in the table today — ``enqueue`` refuses it — and
    the check is here anyway because the canonical string's field discipline
    rests on ``event_type`` being a closed ASCII vocabulary: a type carrying an
    LF could move a field boundary in the signed material."""
    merchant_id, _ = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id, event_type="order.paid\nrefund")
    await db_session.commit()
    sender = _install(monkeypatch, _Sender(_ok()))

    await webhook_delivery.drain_pending_deliveries(db_session)

    row = await _row(db_session, delivery_id)
    assert row.status == "failed"
    assert sender.calls == [], "nothing may be signed with an unvetted event type"
    # Ours, not theirs: nobody's endpoint gets disabled over our bad row.
    assert (await _hook(db_session, merchant_id)).failure_streak == 0


# ---------- the real client, wired in ----------


async def test_a_blocked_address_is_recorded_as_a_policy_refusal_not_a_network_error(
    db_session: AsyncSession,
) -> None:
    """No stub: the **real** ``post_json``, against a URL that resolves to
    loopback. What the delivery log must say is that *we* refused, with no
    status code — a merchant reading "connection failed" would go looking at
    their firewall for a request that never left our network."""
    merchant_id, _ = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id, url="https://127.0.0.1/hooks")
    await db_session.commit()

    assert await webhook_delivery.drain_pending_deliveries(db_session) == 1

    row = await _row(db_session, delivery_id)
    assert row.status == "failed"
    assert row.response_code is None
    assert "AddressNotAllowedError" in (row.last_error or "")
    # Terminal: the row carries a URL snapshot, so a retry aims at the same
    # blocked address however the merchant fixes their configuration.
    assert await webhook_delivery.drain_pending_deliveries(db_session) == 0


async def test_a_url_the_client_will_not_take_is_refused_before_anything_resolves(
    db_session: AsyncSession,
) -> None:
    merchant_id, _ = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id, url="http://hooks.reseller.example/plain")
    await db_session.commit()

    await webhook_delivery.drain_pending_deliveries(db_session)

    row = await _row(db_session, delivery_id)
    assert row.status == "failed"
    assert "UrlNotAllowedError" in (row.last_error or "")


# ---------- ordering, bounds and the batch ----------


async def test_two_events_from_one_transaction_are_delivered_in_enqueue_order(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``created_at`` and ``next_attempt_at`` both default to
    ``CURRENT_TIMESTAMP``, which in Postgres is the **transaction start** — so
    the ``paid`` and ``fulfilling`` rows one merchant placement enqueues are
    byte-identical in both columns, and an ORDER BY over them alone leaves the
    order *unspecified*. A reseller who receives ``fulfilling`` before ``paid``
    reads the later ``paid`` as a status regression and re-opens an order their
    back office closed. ``id`` is a uuid7, so it breaks the tie in enqueue
    order.

    The two rows are inserted **in the opposite order to their ids**, which is
    the whole point: with equal timestamps and no tie-break, Postgres returns
    them in physical order — so a test that inserts them id-ascending passes
    whether the tie-break is there or not. It has been checked that this one
    does not: with the ``id`` term removed from the claim, this test fails.
    (A retry is the real-world way a row's physical order stops matching its
    id: an UPDATE moves it.)
    """
    merchant_id, _ = await _merchant_with_hook(db_session)
    earlier, later = sorted((new_id(), new_id()))
    first = _enqueue(
        db_session, merchant_id, delivery_id=later, payload={"order": "o", "status": "second"}
    )
    second = _enqueue(
        db_session, merchant_id, delivery_id=earlier, payload={"order": "o", "status": "first"}
    )
    assert (first, second) == (later, earlier)
    await db_session.commit()

    stamps = (
        await db_session.execute(
            select(MerchantWebhookDelivery.created_at, MerchantWebhookDelivery.next_attempt_at)
            .where(MerchantWebhookDelivery.merchant_id == merchant_id)
            .order_by(MerchantWebhookDelivery.id)
        )
    ).all()
    assert stamps[0] == stamps[1], "the tie this test exists for did not occur"

    sender = _install(monkeypatch, _Sender(_ok()))
    await webhook_delivery.drain_pending_deliveries(db_session)

    assert [call["headers"]["X-Yupay-Delivery"] for call in sender.calls] == [earlier, later]
    assert [json.loads(call["body"])["status"] for call in sender.calls] == ["first", "second"]


async def test_an_oversized_response_and_error_are_truncated_before_they_are_written(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both columns are length-bounded on purpose (Task 1), so a forgotten
    truncation is a ``DataError`` on the delivery row rather than a silent
    wrong value — which means this test fails loudly if the clip is dropped."""
    merchant_id, _ = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id)
    await db_session.commit()
    _install(monkeypatch, _Sender(_ok(500, "y" * 100_000)))

    await webhook_delivery.drain_pending_deliveries(db_session)

    row = await _row(db_session, delivery_id)
    assert row.response_body is not None
    assert len(row.response_body) == WEBHOOK_RESPONSE_BODY_MAX
    assert len(row.last_error or "") <= WEBHOOK_LAST_ERROR_MAX


async def test_a_long_outbound_error_message_is_clipped_too(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    merchant_id, _ = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id)
    await db_session.commit()
    _install(monkeypatch, _Sender(ConnectFailedError("z" * 5000)))

    await webhook_delivery.drain_pending_deliveries(db_session)

    row = await _row(db_session, delivery_id)
    assert len(row.last_error or "") == WEBHOOK_LAST_ERROR_MAX


async def test_the_batch_is_bounded_and_the_drain_reports_what_it_ran(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``drain_pending_deliveries`` is shaped like ``drain_pending_tasks``: the
    worker drains until a batch comes back empty, so the count is the loop's
    termination condition, not a statistic."""
    merchant_id, _ = await _merchant_with_hook(db_session)
    for _ in range(5):
        _enqueue(db_session, merchant_id)
    await db_session.commit()
    _install(monkeypatch, _Sender(_ok()))

    assert await webhook_delivery.drain_pending_deliveries(db_session, limit=2) == 2
    await db_session.commit()
    assert await webhook_delivery.drain_pending_deliveries(db_session, limit=2) == 2
    await db_session.commit()
    assert await webhook_delivery.drain_pending_deliveries(db_session, limit=2) == 1
    await db_session.commit()
    assert await webhook_delivery.drain_pending_deliveries(db_session, limit=2) == 0


async def test_a_second_drainer_skips_locked_rows_and_takes_the_rest(
    db_engine: Any, db_session: AsyncSession
) -> None:
    """``FOR UPDATE OF merchant_webhook_deliveries SKIP LOCKED`` — and the
    ``of`` is the part worth a test.

    Without it the claim would lock the joined **hook** row too, and a second
    drainer would then skip every remaining delivery of a merchant whose hook
    row the first one happens to hold — one merchant's queue serialised down to
    a single drainer, for a lock that exists to protect nothing here. So: A
    claims one row and holds it; B must come back with the other two of the
    *same* merchant, and must not block waiting for A.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    merchant_id, _ = await _merchant_with_hook(db_session)
    ids = sorted(_enqueue(db_session, merchant_id) for _ in range(3))
    await db_session.commit()

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as other:
        first = await webhook_delivery._claim(db_session, limit=1)
        assert [row[0] for row in first] == [ids[0]]

        second = await asyncio.wait_for(webhook_delivery._claim(other, limit=10), timeout=5)

        assert [row[0] for row in second] == ids[1:]
        await other.rollback()
    await db_session.rollback()


async def test_one_merchants_failures_do_not_stop_anothers_deliveries(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interleaved in one batch, so the ordering and the per-row savepoint are
    both exercised across merchants."""
    good_id, _ = await _merchant_with_hook(db_session)
    # The hook's own URL passes the save-time validator (a literal would be
    # refused there); the *delivery* carries a snapshot that resolves to
    # loopback, which is the shape a rebinding host would take at send time.
    bad_id, _ = await _merchant_with_hook(db_session)
    good = _enqueue(db_session, good_id)
    bad = _enqueue(db_session, bad_id, url="https://127.0.0.1/hooks")
    await db_session.commit()

    async def _route(url: str, **kwargs: Any) -> OutboundResponse:
        if url.startswith("https://127.0.0.1"):
            return await post_json(url, **kwargs)
        return _ok()

    monkeypatch.setattr(webhook_delivery, "post_json", _route)

    assert await webhook_delivery.drain_pending_deliveries(db_session) == 2

    assert (await _row(db_session, good)).status == "delivered"
    assert (await _row(db_session, bad)).status == "failed"
    assert (await _hook(db_session, good_id)).failure_streak == 0
    assert (await _hook(db_session, bad_id)).failure_streak == 1


async def test_the_secret_and_the_signature_never_reach_the_log(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AGENTS §9. The delivery row is the log a merchant's support ticket is
    answered from; the credential that signs it is not part of the answer."""
    merchant_id, secret = await _merchant_with_hook(db_session)
    delivery_id = _enqueue(db_session, merchant_id)
    await db_session.commit()

    lines: list[tuple[str, dict[str, Any]]] = []

    class _Recorder:
        def __getattr__(self, level: str) -> Any:
            def _record(event: str, **fields: Any) -> None:
                lines.append((event, fields))

            return _record

    monkeypatch.setattr(webhook_delivery, "log", _Recorder())
    monkeypatch.setattr(webhook_outcome, "log", _Recorder())
    sender = _install(monkeypatch, _Sender(_ok(500, "boom")))

    await webhook_delivery.drain_pending_deliveries(db_session)

    blob = json.dumps([(event, {k: str(v) for k, v in f.items()}) for event, f in lines])
    assert secret not in blob
    assert sender.calls[0]["headers"]["X-Yupay-Signature"] not in blob
    row = await _row(db_session, delivery_id)
    assert secret not in (row.last_error or "")


async def test_the_worker_reaches_the_drain_through_the_module_facade() -> None:
    """``apps/worker`` must not import ``webhook_delivery`` directly — the
    facade is the module's public interface, and the channel constant travels
    with it so the queue cannot be spelled twice."""
    from yupay.modules.merchants import api as merchants_api

    assert merchants_api.drain_pending_deliveries is webhook_delivery.drain_pending_deliveries
    assert merchants_api.WEBHOOK_QUEUE_CHANNEL == hooks.WEBHOOK_QUEUE_CHANNEL
