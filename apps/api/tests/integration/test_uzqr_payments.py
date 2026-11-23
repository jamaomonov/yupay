"""``uzqr`` as a storefront payment method, end to end (ADR-0106).

UzQR is stood in for by a fake that keeps invoice states, so every branch of
the poll is driven deliberately. Pins: an intent asks for one invoice on the
exact total and the payment carries its QR; a paid invoice pays the order
through the same chokepoint as Payme; an order whose window closed gets its
invoice cancelled at UzQR before we stop looking; a payment the expiry sweep
cancelled is still watched, so a late scan is booked rather than lost; the
payer who beats the cancel is booked; and an outage changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.modules.orders.models import Order
from yupay.modules.orders.service import expire_stale_orders
from yupay.modules.payments import provider_state
from yupay.modules.payments import service as svc
from yupay.modules.payments.gateways.uzqr import UzqrGateway
from yupay.modules.payments.models import Payment
from yupay.modules.payments.p2p_details import payment_out
from yupay.modules.uzqr import client, poll

from tests.integration.test_payments_p2p_gateway import _order

TOTAL = 21_000


@dataclass
class FakeUzqr:
    """Invoice states the way UzQR would hold them."""

    states: dict[str, int] = field(default_factory=dict)
    pay_ids: dict[str, str] = field(default_factory=dict)
    created: list[tuple[str, Decimal]] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    down: bool = False
    #: Paid between our status read and our cancel.
    pays_on_cancel: set[str] = field(default_factory=set)

    async def create_invoice(self, *, external_id: str, amount: Decimal) -> client.Invoice:
        invoice_id = f"INV{len(self.created) + 1}"
        self.created.append((external_id, amount))
        self.states[invoice_id] = client.STATUS_PENDING
        return client.Invoice(invoice_id=invoice_id, qr_text=f"000201-{invoice_id}")

    async def invoice_status(self, invoice_id: str) -> client.InvoiceStatus:
        if self.down:
            raise client.UzqrUnavailableError("down")
        if invoice_id not in self.states:
            raise client.UzqrError("not found", code=client.INVOICE_NOT_FOUND, http_status=404)
        return client.InvoiceStatus(
            invoice_id=invoice_id,
            status=self.states[invoice_id],
            pay_id=self.pay_ids.get(invoice_id),
        )

    async def cancel_invoice(self, invoice_id: str) -> None:
        if invoice_id in self.pays_on_cancel:
            self.pay(invoice_id)
        if self.states.get(invoice_id) == client.STATUS_PAID:
            raise client.UzqrError("paid", code=client.INVOICE_ALREADY_PAID, http_status=400)
        self.cancelled.append(invoice_id)
        self.states[invoice_id] = client.STATUS_REJECTED

    def pay(self, invoice_id: str) -> None:
        self.states[invoice_id] = client.STATUS_PAID
        self.pay_ids[invoice_id] = f"PAY{invoice_id:0>17}"


@pytest.fixture
def uzqr(monkeypatch: pytest.MonkeyPatch) -> FakeUzqr:
    fake = FakeUzqr()
    monkeypatch.setattr(client, "create_invoice", fake.create_invoice)
    monkeypatch.setattr(client, "invoice_status", fake.invoice_status)
    monkeypatch.setattr(client, "cancel_invoice", fake.cancel_invoice)
    monkeypatch.setattr(UzqrGateway, "available", property(lambda _self: True))
    return fake


@pytest.fixture(autouse=True)
async def _switched_on(db_session: AsyncSession) -> None:
    """Migration 0112 seeds the provider ``disabled``; the tests are the owner's switch."""
    await provider_state.set_logical_state(
        db_session, provider="uzqr", state="active", changed_by=new_id()
    )
    await db_session.commit()


@pytest.fixture
def sessions(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_engine, expire_on_commit=False)


async def _paying(db: AsyncSession, **kw: int) -> Payment:
    order_id = await _order(db, total=TOTAL, **kw)
    payment = await svc.create_intent(
        db, order_id=order_id, provider="uzqr", return_url=None, idempotency_key=new_id()
    )
    await db.commit()
    return payment


async def _reload(db: AsyncSession, payment: Payment) -> tuple[Payment, Order]:
    payment_id, order_id = payment.id, payment.order_id
    db.expire_all()
    p = await db.get(Payment, payment_id)
    o = await db.get(Order, order_id)
    assert p is not None
    assert o is not None
    return p, o


async def _lapse(db: AsyncSession, order_id: str) -> None:
    """Move the order's window into the past and let the expiry sweep run."""
    order = await db.get(Order, order_id)
    assert order is not None
    order.expires_at = now() - timedelta(seconds=1)
    await db.commit()
    await expire_stale_orders(db)
    await db.commit()


async def test_an_intent_asks_for_one_invoice_and_carries_its_qr(
    db_session: AsyncSession, uzqr: FakeUzqr
) -> None:
    payment = await _paying(db_session)

    assert payment.status == "pending"
    assert payment.external_id == "uzqr:INV1"
    assert payment.intent_url is None
    [(external_id, amount)] = uzqr.created
    assert amount == Decimal(TOTAL)
    assert len(external_id) == 20
    assert external_id.isalnum()

    out = await payment_out(db_session, payment)
    assert out.uzqr is not None
    assert out.uzqr.qr_text == "000201-INV1"
    assert out.uzqr.amount == Decimal(TOTAL)


async def test_an_intent_with_the_window_nearly_gone_is_refused(
    db_session: AsyncSession, uzqr: FakeUzqr
) -> None:
    order_id = await _order(db_session, total=TOTAL, minutes_left=1)
    with pytest.raises(Exception, match="слишком мало времени"):
        await svc.create_intent(db_session, order_id=order_id, provider="uzqr", return_url=None)
    assert uzqr.created == []


async def test_a_paid_invoice_pays_the_order(
    db_session: AsyncSession, uzqr: FakeUzqr, sessions: async_sessionmaker[AsyncSession]
) -> None:
    payment = await _paying(db_session)
    uzqr.pay("INV1")

    result = await poll.poll_once(sessions)

    assert result.paid == [payment.id]
    p, o = await _reload(db_session, payment)
    assert p.status == "succeeded"
    assert o.status in {"paid", "fulfilling", "fulfilled", "delivered"}
    assert p.extra_metadata["pay_id"] == "PAY" + "INV1".rjust(17, "0")
    assert p.extra_metadata[poll.CLOSED_KEY] is True
    # Closed invoices are not asked about again.
    assert (await poll.poll_once(sessions)).checked == 0
    assert (await payment_out(db_session, p)).uzqr is None


async def test_a_waiting_invoice_inside_the_window_is_left_alone(
    db_session: AsyncSession, uzqr: FakeUzqr, sessions: async_sessionmaker[AsyncSession]
) -> None:
    payment = await _paying(db_session)

    result = await poll.poll_once(sessions)

    assert result.checked == 1
    assert uzqr.cancelled == []
    p, o = await _reload(db_session, payment)
    assert p.status == "pending"
    assert o.status == "pending_payment"


async def test_a_lapsed_order_gets_its_invoice_cancelled_at_uzqr(
    db_session: AsyncSession, uzqr: FakeUzqr, sessions: async_sessionmaker[AsyncSession]
) -> None:
    payment = await _paying(db_session)
    await _lapse(db_session, payment.order_id)
    p, _ = await _reload(db_session, payment)
    # The sweep cancelled our payment; the invoice is still payable at UzQR.
    assert p.status == "cancelled"
    assert poll.CLOSED_KEY not in p.extra_metadata

    await poll.poll_once(sessions)

    assert uzqr.cancelled == ["INV1"]
    p, o = await _reload(db_session, payment)
    assert p.status == "cancelled"
    assert o.status == "expired"
    assert p.extra_metadata[poll.CLOSED_KEY] is True


async def test_a_scan_after_the_sweep_is_booked_not_lost(
    db_session: AsyncSession, uzqr: FakeUzqr, sessions: async_sessionmaker[AsyncSession]
) -> None:
    payment = await _paying(db_session)
    await _lapse(db_session, payment.order_id)
    uzqr.pay("INV1")

    result = await poll.poll_once(sessions)

    assert result.paid == [payment.id]
    p, o = await _reload(db_session, payment)
    assert p.status == "succeeded"
    # The late-payment path: the order leaves ``expired`` for a person to finish.
    assert o.status != "expired"
    assert uzqr.cancelled == []


async def test_the_payer_who_beats_the_cancel_is_booked(
    db_session: AsyncSession, uzqr: FakeUzqr, sessions: async_sessionmaker[AsyncSession]
) -> None:
    payment = await _paying(db_session)
    await _lapse(db_session, payment.order_id)
    uzqr.pays_on_cancel.add("INV1")

    result = await poll.poll_once(sessions)

    assert result.paid == [payment.id]
    p, _ = await _reload(db_session, payment)
    assert p.status == "succeeded"


async def test_a_rejected_invoice_cancels_the_payment(
    db_session: AsyncSession, uzqr: FakeUzqr, sessions: async_sessionmaker[AsyncSession]
) -> None:
    payment = await _paying(db_session)
    uzqr.states["INV1"] = client.STATUS_REJECTED

    await poll.poll_once(sessions)

    p, o = await _reload(db_session, payment)
    assert p.status == "cancelled"
    assert p.extra_metadata[poll.CLOSED_KEY] is True
    assert o.status == "pending_payment"


async def test_an_invoice_uzqr_no_longer_knows_is_closed(
    db_session: AsyncSession, uzqr: FakeUzqr, sessions: async_sessionmaker[AsyncSession]
) -> None:
    payment = await _paying(db_session)
    del uzqr.states["INV1"]

    await poll.poll_once(sessions)

    p, _ = await _reload(db_session, payment)
    assert p.status == "cancelled"
    assert p.extra_metadata[poll.CLOSED_KEY] is True


async def test_an_outage_changes_nothing(
    db_session: AsyncSession, uzqr: FakeUzqr, sessions: async_sessionmaker[AsyncSession]
) -> None:
    payment = await _paying(db_session)
    await _lapse(db_session, payment.order_id)
    uzqr.down = True

    result = await poll.poll_once(sessions)

    assert result.unavailable == 1
    assert uzqr.cancelled == []
    p, _ = await _reload(db_session, payment)
    assert poll.CLOSED_KEY not in p.extra_metadata
    async with sessions() as db:
        assert await poll.open_count(db) == 1
