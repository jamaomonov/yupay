"""Customer wallet top-up: 1:1 deposit via an acquirer (ADR-0058)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.orders.models import Order
from yupay.modules.users.models import TelegramLink, User
from yupay.modules.wallet import funding
from yupay.modules.wallet import service as wallet_svc
from yupay.modules.wallet.service import Leg

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login_user(client: AsyncClient, tg_id: int) -> tuple[str, str]:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    token: str = r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["id"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> None:
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()


async def _topup(
    client: AsyncClient, *, token: str, amount: str, provider: str, key: str
) -> dict[str, object]:
    r = await client.post(
        "/api/v1/wallet/topup",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": key,
            "X-Yupay-Surface": "miniapp",
        },
        json={"amount": amount, "provider": provider},
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def _settle_mock(client: AsyncClient, payment: dict[str, object]) -> None:
    r = await client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {
                "event_id": f"evt-{payment['id']}",
                "payment_id": payment["external_id"],
                "outcome": "succeeded",
            }
        ),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 200, r.text


def _wallet_uzs(overview: dict[str, object]) -> Decimal:
    balances = overview["balances"]
    assert isinstance(balances, list)
    for row in balances:
        assert isinstance(row, dict)
        if row.get("kind") == "user_wallet" and row.get("currency") == "UZS":
            return Decimal(str(row["balance"]))
    return Decimal("0")


async def test_topup_rejects_wallet_provider(integration_client: AsyncClient) -> None:
    token, _ = await _login_user(integration_client, tg_id=901)
    r = await integration_client.post(
        "/api/v1/wallet/topup",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "wallet-topup-reject-wallet",
        },
        json={"amount": "10000", "provider": "wallet"},
    )
    assert r.status_code == 422


async def test_topup_rejects_amount_below_min(integration_client: AsyncClient) -> None:
    token, _ = await _login_user(integration_client, tg_id=902)
    r = await integration_client.post(
        "/api/v1/wallet/topup",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "wallet-topup-reject-minxx",
        },
        json={"amount": "9999", "provider": "mock"},
    )
    assert r.status_code == 422


async def test_topup_settle_credits_once(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token, _user_id = await _login_user(integration_client, tg_id=903)
    first = await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-topup-once-aaa",
    )
    replay = await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-topup-once-aaa",
    )
    assert first["id"] == replay["id"]
    order_id = first["order_id"]
    assert isinstance(order_id, str)

    await _settle_mock(integration_client, first)

    wallet = await integration_client.get(
        "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
    )
    assert wallet.status_code == 200
    assert _wallet_uzs(wallet.json()) == Decimal("10000")

    order = await integration_client.get(
        f"/api/v1/orders/{order_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert order.status_code == 200
    body = order.json()
    assert body["purpose"] == "wallet_topup"
    assert body["status"] == "delivered"
    assert body["items"] == []

    listing = await integration_client.get(
        "/api/v1/orders", headers={"Authorization": f"Bearer {token}"}
    )
    assert listing.status_code == 200
    assert all(row["id"] != order_id for row in listing.json()["items"])

    await _settle_mock(integration_client, first)
    wallet2 = await integration_client.get(
        "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
    )
    assert _wallet_uzs(wallet2.json()) == Decimal("10000")


async def test_topup_refund_reverses_when_unspent(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token, _ = await _login_user(integration_client, tg_id=906)
    payment = await _topup(
        integration_client,
        token=token,
        amount="25000",
        provider="mock",
        key="wallet-topup-refund-ok",
    )
    await _settle_mock(integration_client, payment)

    admin, _ = await _login_user(integration_client, tg_id=907)
    await _grant_admin(db_session, tg_id=907)
    refund = await integration_client.post(
        f"/api/v1/admin/payments/{payment['id']}/refund",
        headers={
            "Authorization": f"Bearer {admin}",
            "Idempotency-Key": "wallet-topup-refund-key1",
        },
        json={},
    )
    assert refund.status_code == 200, refund.text
    wallet = await integration_client.get(
        "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
    )
    assert _wallet_uzs(wallet.json()) == Decimal("0")


async def test_topup_refund_refused_after_spend(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token, user_id = await _login_user(integration_client, tg_id=908)
    payment = await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-topup-refund-spent",
    )
    await _settle_mock(integration_client, payment)

    user_wallet = await wallet_svc.ensure_account(
        db_session,
        owner_type="user",
        owner_id=user_id,
        kind="user_wallet",
        currency="UZS",
    )
    house = await wallet_svc.ensure_account(
        db_session,
        owner_type="house",
        owner_id="house",
        kind="house_payments_received",
        currency="UZS",
    )
    await wallet_svc.post(
        db_session,
        kind="wallet_payment",
        legs=[
            Leg(account_id=user_wallet.id, direction="C", amount=Decimal("10000"), currency="UZS"),
            Leg(account_id=house.id, direction="D", amount=Decimal("10000"), currency="UZS"),
        ],
        idempotency_key="wallet-topup-test-spend-1",
    )
    await db_session.commit()

    admin, _ = await _login_user(integration_client, tg_id=909)
    await _grant_admin(db_session, tg_id=909)
    refund = await integration_client.post(
        f"/api/v1/admin/payments/{payment['id']}/refund",
        headers={
            "Authorization": f"Bearer {admin}",
            "Idempotency-Key": "wallet-topup-refund-spentk",
        },
        json={},
    )
    assert refund.status_code == 409

    leftover = (
        await db_session.execute(select(Order).where(Order.id == payment["order_id"]))
    ).scalar_one()
    assert leftover.purpose == "wallet_topup"


async def test_checkout_refuses_a_key_already_spent_on_a_deposit(
    integration_client: AsyncClient,
) -> None:
    """The guard `create_topup` has, in the other direction.

    Both live in `orders` and share one partial unique on
    ``(user_id, idempotency_key)``. `create_topup` checks the purpose of what
    it finds and answers 409; checkout replayed on the key alone, so a key
    already spent on a deposit would have handed the buyer that deposit back
    as though it were their purchase — no items, nothing bought.

    The SKU here is deliberately nonexistent: the replay short-circuit runs
    before any SKU is loaded, so reaching a SKU error at all would already
    mean the guard fired.
    """
    token, _ = await _login_user(integration_client, tg_id=910)
    await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-topup-crosstalk-1",
    )
    order = await integration_client.post(
        "/api/v1/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "wallet-topup-crosstalk-1",
        },
        json={
            "currency": "USD",
            "items": [{"sku_id": "00000000-0000-7000-8000-000000000000", "qty": 1}],
        },
    )
    assert order.status_code == 409, order.text


async def test_admin_payment_list_says_a_deposit_is_a_deposit(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Otherwise a deposit and a sale look identical in the payments list."""
    token, _ = await _login_user(integration_client, tg_id=911)
    payment = await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-topup-adminlist-1",
    )
    admin, _ = await _login_user(integration_client, tg_id=912)
    await _grant_admin(db_session, tg_id=912)

    order_id = payment["order_id"]
    assert isinstance(order_id, str)
    listing = await integration_client.get(
        "/api/v1/admin/payments",
        headers={"Authorization": f"Bearer {admin}"},
        params={"order_id": order_id},
    )
    assert listing.status_code == 200, listing.text
    rows = listing.json()["items"]
    assert len(rows) == 1
    assert rows[0]["order_purpose"] == "wallet_topup"


async def test_a_deposit_cannot_be_paid_from_the_wallet_itself(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """`BLOCKED_PROVIDERS` guards `/wallet/topup`; the charge happens elsewhere.

    `create_intent` only checks that the order is awaiting payment, so a
    customer who abandons the acquirer — which leaves the order
    `pending_payment` by design — can point a second intent at the same
    deposit with `provider: "wallet"`. The balance nets to zero, but each
    lap debits `house_payments_received` for money no acquirer ever sent and
    records a delivered deposit, and it can be repeated indefinitely.
    """
    token, user_id = await _login_user(integration_client, tg_id=913)

    # Fund the balance so the gateway gets past its sufficiency check — the
    # point is the missing purpose guard, not an empty wallet.
    user_wallet = await wallet_svc.ensure_account(
        db_session,
        owner_type="user",
        owner_id=user_id,
        kind="user_wallet",
        currency="UZS",
    )
    house = await wallet_svc.ensure_account(
        db_session,
        owner_type="house",
        owner_id="house",
        kind="house_payments_received",
        currency="UZS",
    )
    await wallet_svc.post(
        db_session,
        kind="admin.adjust",
        legs=[
            Leg(account_id=user_wallet.id, direction="D", amount=Decimal("50000"), currency="UZS"),
            Leg(account_id=house.id, direction="C", amount=Decimal("50000"), currency="UZS"),
        ],
        idempotency_key="wallet-selffund-seed-1",
    )
    await db_session.commit()

    deposit = await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-selffund-order-1",
    )

    # The customer abandons the acquirer's page. That cancels our payment row
    # and — by design, see `cancel_pending_provider_payment` — leaves the order
    # awaiting payment, so `_find_active_payment` no longer guards the slot.
    from yupay.modules.payments.models import Payment

    await db_session.execute(
        update(Payment).where(Payment.order_id == deposit["order_id"]).values(status="cancelled")
    )
    await db_session.commit()

    intent = await integration_client.post(
        "/api/v1/payments/intents",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "wallet-selffund-intent1",
        },
        json={"order_id": deposit["order_id"], "provider": "wallet"},
    )
    assert intent.status_code >= 400, (
        "a deposit must not be payable from the balance it is meant to fund; "
        f"got {intent.status_code}: {intent.text}"
    )


async def test_the_operators_note_stays_out_of_the_customers_history(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The admin form calls this reason an audit entry; it was reaching the
    customer's wallet history through ``extra_metadata``.

    The operator still needs it, so the admin ledger keeps carrying it.
    """
    token, user_id = await _login_user(integration_client, tg_id=914)
    admin, _ = await _login_user(integration_client, tg_id=915)
    await _grant_admin(db_session, tg_id=915)

    note = "INCIDENT_CREDIT: клиент скандалил, дали компенсацию"
    adjust = await integration_client.post(
        "/api/v1/admin/wallet/adjust",
        headers={"Authorization": f"Bearer {admin}"},
        json={
            "user_id": user_id,
            "kind": "user_wallet",
            "currency": "UZS",
            "amount": "50000",
            "reason": note,
            "idempotency_key": "wallet-note-privacy-1",
        },
    )
    assert adjust.status_code == 200, adjust.text

    mine = await integration_client.get(
        "/api/v1/wallet/transactions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert mine.status_code == 200, mine.text
    body = mine.text
    assert "скандалил" not in body, "the operator's note reached the customer"
    assert "INCIDENT_CREDIT" not in body
    rows = mine.json()["items"]
    assert len(rows) == 1
    assert rows[0]["extra_metadata"] == {}
    assert rows[0]["actor"] is None, "who moved the money is an internal fact"
    # The movement itself is still fully described.
    assert rows[0]["kind"] == "admin.adjust"
    assert rows[0]["postings"]

    # The operator has lost nothing.
    ledger = await integration_client.get(
        f"/api/v1/admin/wallet/{user_id}",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert ledger.status_code == 200, ledger.text
    assert note in ledger.text


async def test_a_replayed_key_with_a_different_amount_is_refused(
    integration_client: AsyncClient,
) -> None:
    """A key names one request. Reusing it for another is not a replay.

    Checking only the purpose meant a client with a stale key was handed a
    hosted checkout for the previous figure — money moving on an amount nobody
    asked for on this call.
    """
    token, _ = await _login_user(integration_client, tg_id=916)
    await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-replay-amount-01",
    )

    again = await integration_client.post(
        "/api/v1/wallet/topup",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "wallet-replay-amount-01",
            "X-Yupay-Surface": "miniapp",
        },
        json={"amount": "500000", "provider": "mock"},
    )
    assert again.status_code == 409, again.text


async def test_a_replayed_key_with_a_different_acquirer_is_refused(
    integration_client: AsyncClient,
) -> None:
    """Same amount, different rail — the customer would be sent to the first
    acquirer's page while believing they had picked the second."""
    token, _ = await _login_user(integration_client, tg_id=917)
    await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-replay-rail-001",
    )

    again = await integration_client.post(
        "/api/v1/wallet/topup",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "wallet-replay-rail-001",
            "X-Yupay-Surface": "miniapp",
        },
        json={"amount": "10000", "provider": "payme"},
    )
    assert again.status_code == 409, again.text


async def test_the_same_request_still_replays(integration_client: AsyncClient) -> None:
    """The guard must not break what idempotency is for."""
    token, _ = await _login_user(integration_client, tg_id=918)
    first = await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-replay-same-001",
    )
    again = await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-replay-same-001",
    )
    assert first["id"] == again["id"]


def _blind_precheck_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the next duplicate-key lookup miss, the way a real race does.

    Two concurrent calls carrying one key both run the pre-check before either
    has inserted, so both see nothing and both try to insert. The loser is the
    one the unique index rejects, and it lands in the ``IntegrityError`` branch
    — the only place the guard runs for it. Blinding exactly the first lookup
    reproduces that ordering deterministically; the re-select inside the branch
    is the second call and sees the winner's row, as it would in production.
    """
    real = funding._existing_topup_order
    seen = {"n": 0}

    async def flaky(*args: object, **kwargs: object) -> Order | None:
        seen["n"] += 1
        if seen["n"] == 1:
            return None
        return await real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(funding, "_existing_topup_order", flaky)


async def test_the_losing_side_of_a_race_is_still_checked(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The race path applies the same guard, not a looser one.

    Both callers miss the pre-check, so the one the unique index rejects
    reaches the ``IntegrityError`` branch. Without the check there it would be
    handed a hosted checkout for the winner's figure — the customer paying an
    amount this call never named.
    """
    token, _ = await _login_user(integration_client, tg_id=940)
    await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-race-amount-01",
    )

    _blind_precheck_once(monkeypatch)
    again = await integration_client.post(
        "/api/v1/wallet/topup",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "wallet-race-amount-01",
            "X-Yupay-Surface": "miniapp",
        },
        json={"amount": "500000", "provider": "mock"},
    )
    assert again.status_code == 409, again.text


async def test_the_losing_side_of_a_race_still_replays_when_it_agrees(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard on the race path must not break idempotency either.

    A genuine double-submit — one key, one amount, one rail — is what
    idempotency exists for, and losing the insert race is not a reason to
    refuse it. The loser gets the winner's payment, and no second order.
    """
    token, _ = await _login_user(integration_client, tg_id=941)
    first = await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-race-same-0001",
    )

    _blind_precheck_once(monkeypatch)
    again = await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-race-same-0001",
    )
    assert first["id"] == again["id"]


async def test_a_race_that_cannot_find_the_winner_refuses(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A duplicate the re-select cannot explain is refused, not retried.

    If the insert is rejected and the row still cannot be read, something other
    than an ordinary replay is going on. The one thing this must not do is
    carry on and create a second deposit for a key that already has one.
    """
    token, _ = await _login_user(integration_client, tg_id=942)
    await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-race-blind-001",
    )

    async def blind(*args: object, **kwargs: object) -> Order | None:
        return None

    monkeypatch.setattr(funding, "_existing_topup_order", blind)
    again = await integration_client.post(
        "/api/v1/wallet/topup",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "wallet-race-blind-001",
            "X-Yupay-Surface": "miniapp",
        },
        json={"amount": "10000", "provider": "mock"},
    )
    assert again.status_code == 409, again.text


async def test_replaying_a_key_after_the_money_landed_returns_the_paid_payment(
    integration_client: AsyncClient,
) -> None:
    """A replay after settlement returns the settled payment, and credits once.

    Once the webhook has landed there is no *active* intent left to hand back —
    the payment is ``succeeded`` — so the lookup that serves every other replay
    finds nothing. Falling through to "create one" would open a second checkout
    for a deposit already paid; the customer would be invited to pay twice for
    a balance already credited.
    """
    token, _ = await _login_user(integration_client, tg_id=943)
    first = await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-replay-paid-01",
    )
    await _settle_mock(integration_client, first)

    again = await _topup(
        integration_client,
        token=token,
        amount="10000",
        provider="mock",
        key="wallet-replay-paid-01",
    )
    assert again["id"] == first["id"]
    assert again["status"] == "succeeded"

    wallet = await integration_client.get(
        "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
    )
    assert _wallet_uzs(wallet.json()) == Decimal("10000")
