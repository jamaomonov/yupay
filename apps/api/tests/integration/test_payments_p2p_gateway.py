"""``p2p`` as a storefront payment method (ADR-0097).

Pins the gateway's contract end to end: an intent holds the order's exact
total on a card for the order's own window and the payment carries where to
send it; a retried intent is the same payment; a disabled provider and an
unconnected bot both refuse before anything is held; a busy amount is bumped
and the bumped figure is what the payer sees; and the HUMO notification that
matches the hold pays the order through the same chokepoint Payme uses.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import ConflictError
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.p2p import intake, reservations
from yupay.modules.p2p.models import P2PReservation
from yupay.modules.p2p.settings import load_settings
from yupay.modules.payments import provider_state
from yupay.modules.payments import service as svc
from yupay.modules.payments.gateways.p2p import P2PGateway
from yupay.modules.payments.models import Payment
from yupay.modules.payments.p2p_details import payment_out
from yupay.modules.users.models import User

from tests.integration.p2p_fixtures import _card, _fixed_rate  # noqa: F401  (autouse rate)
from tests.integration.test_p2p_intake import HUMO_ID, OWNER_ID, _bank, _credit, _update

pytestmark = pytest.mark.asyncio

TOTAL = 21_113


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The webhook secret is what ``available`` reads; settings are cached per
    process, so the house pattern patches the property rather than the env."""
    monkeypatch.setattr(P2PGateway, "available", property(lambda _self: True))


@pytest.fixture(autouse=True)
async def _switched_on(db_session: AsyncSession) -> None:
    """Migration 0097 seeds the provider ``disabled`` so a deploy does not put
    the method on checkout before the bot is connected; the tests stand in for
    the admin's switch."""
    await provider_state.set_logical_state(
        db_session, provider="p2p", state="active", changed_by=new_id()
    )
    await db_session.commit()


async def _connected(db: AsyncSession) -> None:
    s = await load_settings(db)
    s.humo_bot_user_id = HUMO_ID
    s.owner_telegram_user_id = OWNER_ID
    s.business_connection_id = "bc1"
    await db.flush()


async def _order(db: AsyncSession, *, total: int = TOTAL, minutes_left: int = 10) -> str:
    """A pending UZS order with one line, the way checkout leaves it."""
    slug = uuid.uuid4().hex[:8]
    user_id = str(uuid.uuid4())
    db.add(User(id=user_id, email=f"u-{slug}@example.com", locale="ru", roles=[]))
    await db.flush()
    cat_id, brand_id, product_id, sku_id = (str(uuid.uuid4()) for _ in range(4))
    db.add(Category(id=cat_id, slug=f"c-{slug}"))
    await db.flush()
    db.add(Brand(id=brand_id, slug=f"b-{slug}", category_id=cat_id))
    await db.flush()
    db.add(Product(id=product_id, slug=f"p-{slug}", brand_id=brand_id, kind="top_up"))
    await db.flush()
    db.add(Sku(id=sku_id, product_id=product_id, sku_code=f"sku-{slug}", price_usd=Decimal("1.79")))
    await db.flush()
    order_id = str(uuid.uuid4())
    now_ = datetime.now(UTC)
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            guest_email=None,
            status="pending_payment",
            currency="UZS",
            total_usd=Decimal("1.79"),
            total_charged=Decimal(total),
            created_at=now_,
            expires_at=now_ + timedelta(minutes=minutes_left),
        )
    )
    await db.flush()
    db.add(
        OrderItem(
            id=str(uuid.uuid4()),
            order_id=order_id,
            sku_id=sku_id,
            qty=1,
            unit_price_usd=Decimal("1.79"),
        )
    )
    await db.commit()
    return order_id


async def test_an_intent_holds_the_total_for_the_orders_window(db_session: AsyncSession) -> None:
    await _card(db_session)
    await _connected(db_session)
    order_id = await _order(db_session)

    payment = await svc.create_intent(
        db_session, order_id=order_id, provider="p2p", return_url=None, idempotency_key="k-1"
    )
    await db_session.commit()

    assert payment.provider == "p2p"
    assert payment.status == "pending"
    assert payment.intent_url is None
    assert payment.external_id is not None
    assert payment.external_id.startswith("p2p:")
    number = payment.external_id.removeprefix("p2p:")
    reservation = (
        await db_session.execute(select(P2PReservation).where(P2PReservation.number == number))
    ).scalar_one()
    assert reservation.purpose == "order"
    assert reservation.order_id == order_id
    assert reservation.merchant_id is None
    assert reservation.amount_uzs == TOTAL
    order = await db_session.get(Order, order_id)
    assert order is not None
    assert reservation.expires_at == order.expires_at

    out = await payment_out(db_session, payment)
    assert out.p2p is not None
    assert out.p2p.pan == "9860 3501 4602 3311"
    assert out.p2p.holder_name == "OMONOV J"
    assert out.p2p.amount_uzs == TOTAL
    assert out.p2p.reservation_number == number


async def test_a_retried_intent_is_the_same_payment_and_hold(db_session: AsyncSession) -> None:
    await _card(db_session)
    await _connected(db_session)
    order_id = await _order(db_session)
    first = await svc.create_intent(
        db_session, order_id=order_id, provider="p2p", return_url=None, idempotency_key="k-a"
    )
    await db_session.commit()

    same_key = await svc.create_intent(
        db_session, order_id=order_id, provider="p2p", return_url=None, idempotency_key="k-a"
    )
    new_key = await svc.create_intent(
        db_session, order_id=order_id, provider="p2p", return_url=None, idempotency_key="k-b"
    )
    await db_session.commit()

    assert same_key.id == first.id
    assert new_key.id == first.id  # the active payment is reused, no second hold
    holds = (
        await db_session.execute(select(P2PReservation).where(P2PReservation.order_id == order_id))
    ).scalars()
    assert len(list(holds)) == 1


async def test_a_disabled_provider_refuses_before_holding(db_session: AsyncSession) -> None:
    await _card(db_session)
    await _connected(db_session)
    await provider_state.set_logical_state(
        db_session, provider="p2p", state="disabled", changed_by=new_id()
    )
    order_id = await _order(db_session)

    with pytest.raises(ConflictError):
        await svc.create_intent(
            db_session, order_id=order_id, provider="p2p", return_url=None, idempotency_key="k-d"
        )
    assert (
        await db_session.scalar(select(P2PReservation).where(P2PReservation.order_id == order_id))
    ) is None


async def test_an_unconnected_bot_refuses_with_a_reason(db_session: AsyncSession) -> None:
    await _card(db_session)
    order_id = await _order(db_session)

    with pytest.raises(ConflictError) as exc:
        await svc.create_intent(
            db_session, order_id=order_id, provider="p2p", return_url=None, idempotency_key="k-u"
        )
    assert "недоступен" in str(exc.value)


async def test_a_held_amount_is_bumped_and_the_payer_sees_the_bumped_figure(
    db_session: AsyncSession,
) -> None:
    await _card(db_session)
    await _connected(db_session)
    # Somebody else holds the exact total on the only card.
    other = await _order(db_session)
    await reservations.reserve_for_order(
        db_session,
        order_id=other,
        amount_uzs=TOTAL,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    await db_session.commit()
    order_id = await _order(db_session)

    payment = await svc.create_intent(
        db_session, order_id=order_id, provider="p2p", return_url=None, idempotency_key="k-bump"
    )
    await db_session.commit()

    out = await payment_out(db_session, payment)
    assert out.p2p is not None
    assert out.p2p.amount_uzs == TOTAL + 1
    assert payment.extra_metadata["amount_uzs"] == TOTAL + 1


async def test_the_matching_transfer_pays_the_order(db_session: AsyncSession) -> None:
    await _card(db_session)
    await _connected(db_session)
    order_id = await _order(db_session)
    payment = await svc.create_intent(
        db_session, order_id=order_id, provider="p2p", return_url=None, idempotency_key="k-pay"
    )
    await db_session.commit()
    number = (payment.external_id or "").removeprefix("p2p:")
    reservation = (
        await db_session.execute(select(P2PReservation).where(P2PReservation.number == number))
    ).scalar_one()

    res = await intake.ingest_update(
        db_session,
        _update(41, _credit("21.113,00", _bank(reservation.created_at), "1.100.000,00")),
        received_at=reservation.created_at + timedelta(minutes=1),
    )
    await db_session.commit()

    assert res.status == "matched"
    assert res.reservation_number == number
    payment_id, reservation_id = payment.id, reservation.id
    db_session.expire_all()
    paid = await db_session.get(Payment, payment_id)
    assert paid is not None
    assert paid.status == "succeeded"
    order = await db_session.get(Order, order_id)
    assert order is not None
    assert order.status in ("paid", "fulfilling")
    assert order.paid_at is not None
    held = await db_session.get(P2PReservation, reservation_id)
    assert held is not None
    assert held.status == "paid"
    # Paid: the instructions are gone from the payment.
    assert (await payment_out(db_session, paid)).p2p is None


async def test_an_expired_hold_is_remade_on_the_next_intent(db_session: AsyncSession) -> None:
    """A pending hold whose window closed does not come back as the open one:
    it is expired in place and the order gets a fresh hold."""
    await _card(db_session)
    await _connected(db_session)
    order_id = await _order(db_session)
    stale = await reservations.reserve_for_order(
        db_session,
        order_id=order_id,
        amount_uzs=TOTAL,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    await db_session.commit()
    stale_id = stale.id

    fresh = await reservations.reserve_for_order(
        db_session,
        order_id=order_id,
        amount_uzs=TOTAL,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    await db_session.commit()
    fresh_id = fresh.id

    assert fresh_id != stale_id
    db_session.expire_all()
    old = await db_session.get(P2PReservation, stale_id)
    assert old is not None
    assert old.status == "expired"


async def test_a_rate_outage_refuses_the_hold(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No USD figure for the row → no hold, and the error names the rate."""
    from yupay.core.errors import UpstreamUnavailableError
    from yupay.modules.pricing.fx_guard import RateRejected

    async def _rejected(*_a: object, **_k: object) -> Decimal:
        raise RateRejected("stale")

    monkeypatch.setattr(reservations, "guarded_usd_rate", _rejected)
    await _card(db_session)
    order_id = await _order(db_session)

    with pytest.raises(UpstreamUnavailableError) as exc:
        await reservations.reserve_for_order(
            db_session,
            order_id=order_id,
            amount_uzs=TOTAL,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    assert exc.value.extra["code"] == "fx_unavailable"


async def test_no_eligible_card_means_a_busy_amount(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no card can take the amount at any bump, the hold is refused
    with the code the gateway turns into «занят — попробуйте позже»."""
    from yupay.core.errors import UpstreamUnavailableError

    async def _none(*_a: object, **_k: object) -> list[tuple[object, int]]:
        return []

    monkeypatch.setattr(reservations, "eligible_cards", _none)
    await _card(db_session)
    order_id = await _order(db_session)

    with pytest.raises(UpstreamUnavailableError) as exc:
        await reservations.reserve_for_order(
            db_session,
            order_id=order_id,
            amount_uzs=TOTAL,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    assert exc.value.extra["code"] == "p2p_amount_busy"


async def test_a_hold_without_a_payment_leaves_the_transfer_unmatched(
    db_session: AsyncSession,
) -> None:
    """An order hold with no ``p2p`` payment behind it (the intent never
    committed) must not swallow the money: the transfer lands unmatched
    with an alert, and the hold stays open for the operator to read."""
    await _card(db_session)
    await _connected(db_session)
    order_id = await _order(db_session)
    reservation = await reservations.reserve_for_order(
        db_session,
        order_id=order_id,
        amount_uzs=TOTAL,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    await db_session.commit()
    number, created_at, reservation_id = (
        reservation.number,
        reservation.created_at,
        reservation.id,
    )

    res = await intake.ingest_update(
        db_session,
        _update(51, _credit("21.113,00", _bank(created_at), "1.100.000,00")),
        received_at=created_at + timedelta(minutes=1),
    )
    await db_session.commit()

    assert res.status == "unmatched"
    assert [kind for kind, _ in res.alerts] == ["p2p_order_payment_missing"]
    assert number in res.alerts[0][1]
    db_session.expire_all()
    held = await db_session.get(P2PReservation, reservation_id)
    assert held is not None
    assert held.status == "pending"
    order = await db_session.get(Order, order_id)
    assert order is not None
    assert order.status == "pending_payment"
