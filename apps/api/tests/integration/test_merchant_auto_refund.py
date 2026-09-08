"""The automatic deposit refund (Merchant B2B M3b, Task 3).

When a supplier fails a merchant order **and gave our money back**, the
reseller's deposit gets it back without an operator. When the supplier kept the
money, or we cannot tell, nothing moves and a human decides. The whole task is
that one distinction, so the file is organised around what can go wrong with
it rather than around the happy path:

* **only ``RETURNED`` pays** — ``SPENT`` and ``UNKNOWN`` refund nothing, and
  are visibly parked where an operator can find them;
* **exactly once**, under a re-driven fulfilment, an admin retry, and two real
  drainers on two connections;
* **the amount is the charge's**, read off the ledger transaction we posted,
  not off the order line — the list price is allowed to move between quote and
  charge and an unpaid order must refund nothing;
* **a refund cannot deliver free goods** — the retry that follows one is
  refused, because ``charge_deposit`` replays its key and would debit nothing
  the second time;
* **a refund that cannot post leaves the failure refundable** — never a
  permanent ``UNKNOWN``, which no operator path can clear;
* **retail is untouched** — ``INVENTORY_FAILURE_MONEY_OUTCOME`` is
  ``RETURNED`` and fires on every storefront order that runs the warehouse
  dry, which is the most common failure in the codebase.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import CoroutineType
from typing import Any
from urllib.parse import quote, urlencode

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core.errors import ConflictError
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers import FulfillResult, MoneyOutcome
from yupay.modules.fulfillment.suppliers.mock import MockFulfiller
from yupay.modules.merchants import deposit as merchant_deposit
from yupay.modules.merchants import refund as merchant_refund
from yupay.modules.merchants.models import MerchantWebhookDelivery
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.sourcing.models import SkuSourcingRule
from yupay.modules.users.models import TelegramLink, User
from yupay.modules.wallet.models import WalletTransaction

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
ORDERS_PATH = "/merchant/v1/orders"
TXN_PATH = "/merchant/v1/transactions"

#: Cost $1.00 at 7% markup — what every order below is charged.
PRICE = "1.07"
#: What the deposit is funded with before each order.
FUNDING = "10.00"


# ---------- harness ----------


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


@pytest.fixture
async def admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    """Log a Telegram user in and grant it the admin role."""
    user_json = json.dumps({"id": 97, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await integration_client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == 97)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


#: What ``_dispatch_alert`` is actually handed. ``collections.abc.Coroutine``
#: is the *protocol* and has no ``cr_code``; ``types.CoroutineType`` is the
#: concrete object an ``async def`` call returns and does. mypy caught the
#: difference — under ``mypy apps``, which is the command CI runs and the one
#: this file was first verified without.
#:
#: A PEP 695 ``type`` alias, whose right-hand side is evaluated **lazily** —
#: ``CoroutineType`` is not subscriptable at runtime, and a plain assignment
#: would be evaluated eagerly and raise. (``from __future__ import
#: annotations`` defers annotations, not assignments.)
type Alert = CoroutineType[Any, Any, None]


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Alert]]:
    """Capture the ops alerts the saga dispatches, by coroutine name.

    ``_dispatch_alert`` schedules on the running loop and the alert itself
    short-circuits on an empty bot token, so the assertions here are about
    *which* alert fired, not its text — the text is a unit test's job. Every
    captured coroutine is closed at teardown so nothing warns about a
    coroutine that was never awaited.
    """
    captured: list[Alert] = []
    monkeypatch.setattr(ff_svc, "_dispatch_alert", captured.append)
    yield captured
    for coro in captured:
        coro.close()


def _merchant_alerts(alerts: list[Alert]) -> list[str]:
    """Only the alerts this task adds.

    Every terminal failure already raises the saga's own
    ``_alert_fulfillment_error``, which predates M3b and is not what these
    assertions are about.
    """
    return [c.cr_code.co_name for c in alerts if c.cr_code.co_name.startswith("_alert_merchant")]


async def _new_merchant(
    client: AsyncClient, headers: dict[str, str], title: str = "Reseller"
) -> str:
    r = await client.post("/api/v1/admin/merchants", headers=headers, json={"title": title})
    assert r.status_code == 201, r.text
    merchant_id: str = r.json()["id"]
    return merchant_id


async def _new_key(
    client: AsyncClient, headers: dict[str, str], merchant_id: str
) -> tuple[str, str]:
    r = await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/api-keys",
        headers=headers,
        json={"label": "server"},
    )
    assert r.status_code == 201, r.text
    payload = r.json()
    return payload["key_id"], payload["secret"]


async def _credit(
    client: AsyncClient,
    headers: dict[str, str],
    merchant_id: str,
    amount: str,
    *,
    order_id: str | None = None,
    key: str | None = None,
) -> Response:
    body: dict[str, Any] = {"amount": amount}
    if order_id is not None:
        body["order_id"] = order_id
    return await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**headers, "Idempotency-Key": key or f"settle-{new_id()}"},
        json=body,
    )


def _signed(
    key_id: str, secret: str, *, method: str = "GET", path: str, query: str = "", body: bytes = b""
) -> dict[str, str]:
    ts = str(int(time.time()))
    message = "\n".join(
        (ts, method.upper(), path, query, hashlib.sha256(body).hexdigest())
    ).encode()
    return {
        "X-Merchant-Key": key_id,
        "X-Merchant-Timestamp": ts,
        "X-Merchant-Signature": hmac.new(
            secret.encode("utf-8"), message, hashlib.sha256
        ).hexdigest(),
        "Content-Type": "application/json",
    }


async def _post_order(
    client: AsyncClient, key_id: str, secret: str, payload: dict[str, Any]
) -> Response:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return await client.post(
        ORDERS_PATH,
        content=body,
        headers=_signed(key_id, secret, method="POST", path=ORDERS_PATH, body=body),
    )


async def _read_order(
    client: AsyncClient, key_id: str, secret: str, merchant_order_id: str
) -> Response:
    path = f"{ORDERS_PATH}/{quote(merchant_order_id, safe='')}"
    return await client.get(path, headers=_signed(key_id, secret, path=path))


async def _statement(client: AsyncClient, key_id: str, secret: str) -> list[dict[str, Any]]:
    r = await client.get(TXN_PATH, headers=_signed(key_id, secret, path=TXN_PATH))
    assert r.status_code == 200, r.text
    items: list[dict[str, Any]] = r.json()["items"]
    return items


async def _seed_sku(db: AsyncSession, *, n: int = 1, route: str = "mock") -> str:
    """One catalog chain at $1.00 cost / 7 % markup, pinned to one route.

    The sourcing rule is what makes the failure reproducible: without it a
    ``top_up`` SKU with no supplier mapping routes to the manual admin queue
    and never reaches a fulfiller at all.
    """
    category = Category(
        id=new_id(),
        slug=f"cat-{n}-{new_id()[-8:]}",
        sort_order=n,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=f"Категория {n}")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-{n}-{new_id()[-8:]}",
        category_id=category.id,
        sort_order=n,
        active=True,
        visible_b2b=True,
        translations=[BrandTranslation(locale="ru", name=f"Бренд {n}")],
    )
    product = Product(
        id=new_id(),
        slug=f"product-{n}-{new_id()[-8:]}",
        brand_id=brand.id,
        kind="top_up",
        sort_order=n,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name=f"Продукт {n}")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"sku-{n}-{new_id()[-8:]}",
        denomination=f"{n}00 UC",
        region="GLOBAL",
        price_usd=Decimal("9.99"),
        cost_usdt=Decimal("1.000000"),
        visible_b2b=True,
        b2b_markup_pct=Decimal("7"),
        sort_order=0,
        active=True,
    )
    db.add_all([category, brand, product, sku])
    # Flushed before the rule: ``sku_sourcing_rules.sku_id`` is a plain FK with
    # no ORM relationship, so the unit of work has no reason to order the two
    # inserts and would send the rule first.
    await db.flush()
    if route == "inventory":
        db.add(SkuSourcingRule(sku_id=sku.id, mode="force_inventory"))
    elif route == "auto":
        pass
    else:
        db.add(SkuSourcingRule(sku_id=sku.id, mode="force_supplier", supplier_slug=route))
    return sku.id


async def _placed(
    client: AsyncClient,
    headers: dict[str, str],
    db: AsyncSession,
    *,
    merchant_order_id: str,
    title: str = "Reseller",
    n: int = 1,
    route: str = "mock",
) -> tuple[str, str, str, str]:
    """A merchant, a key, a funded deposit and one placed (``fulfilling``) order.

    Returns ``(merchant_id, key_id, secret, order_id)``. The order's task is
    left ``pending`` — the merchant path is enqueue-only by construction — so
    each test drives it with whatever failure it is about.
    """
    merchant_id = await _new_merchant(client, headers, title=title)
    key_id, secret = await _new_key(client, headers, merchant_id)
    assert (await _credit(client, headers, merchant_id, FUNDING)).status_code == 201
    sku_id = await _seed_sku(db, n=n, route=route)
    await db.commit()
    r = await _post_order(
        client,
        key_id,
        secret,
        {"merchant_order_id": merchant_order_id, "sku_id": sku_id, "expected_price": PRICE},
    )
    assert r.status_code == 201, r.text
    order_id: str = r.json()["order_id"]
    return merchant_id, key_id, secret, order_id


def _failing_mock(
    monkeypatch: pytest.MonkeyPatch,
    outcome: MoneyOutcome | None,
    *,
    error: str = "supplier refused",
) -> None:
    """Make every mock fulfilment fail with this money outcome.

    ``None`` with ``error="supplier_low_balance"`` is the **stall**: a failed
    result that is not a terminal failure, records no money outcome, and
    deliberately leaves the order item ``in_progress``.
    """

    async def _fail(
        self: MockFulfiller,
        *,
        db: AsyncSession,
        order: Order,
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        return FulfillResult(
            outcome="failed",
            external_order_id=None,
            artifact_kind=None,
            artifact=None,
            error=error,
            extra_metadata={},
            money_outcome=outcome,
        )

    monkeypatch.setattr(MockFulfiller, "fulfill", _fail)


async def _balance(db: AsyncSession, merchant_id: str) -> Decimal:
    return await merchant_deposit.deposit_balance(db, merchant_id=merchant_id)


async def _refund_rows(db: AsyncSession, order_id: str) -> list[WalletTransaction]:
    return list(
        (
            await db.execute(
                select(WalletTransaction).where(
                    WalletTransaction.kind == merchant_refund.REFUND_KIND,
                    WalletTransaction.reference_id == order_id,
                )
            )
        )
        .scalars()
        .all()
    )


@pytest.fixture
async def second_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A second session on the same engine — a second worker replica.

    The concurrency proof needs two real connections racing one unique index,
    not two coroutines sharing one transaction.
    """
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


# ---------- RETURNED refunds, once, for what we charged ----------


async def test_a_returned_failure_returns_the_charge_to_the_deposit(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """The whole feature: the deposit ends where it started, in one posting."""
    merchant_id, _key, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-returned"
    )
    assert await _balance(db_session, merchant_id) == Decimal(FUNDING) - Decimal(PRICE)

    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    assert await ff_svc.drain_pending_tasks(db_session) == 1
    await db_session.commit()

    assert await _balance(db_session, merchant_id) == Decimal(FUNDING)
    rows = await _refund_rows(db_session, order_id)
    assert len(rows) == 1
    assert rows[0].reference_type == merchant_deposit.ORDER_REFERENCE_TYPE
    # Ruling 6: a key that collided with the charge's would replay the charge
    # and every caller above would treat that as the refund.
    charge = (
        await db_session.execute(
            select(WalletTransaction).where(
                WalletTransaction.idempotency_key == merchant_deposit.charge_key(order_id)
            )
        )
    ).scalar_one()
    assert rows[0].id != charge.id
    assert _merchant_alerts(alerts) == []


async def test_the_refund_is_what_we_charged_not_what_the_line_says_now(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """Ruling 5: the ledger is the only authority on what we took.

    The list price is allowed to move between quote and charge (M2's ±2 %
    rule), so the order line is not the amount. Moving it here is what makes
    an implementation that reads ``unit_price_usd`` fail.
    """
    merchant_id, _key, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-price-moved"
    )
    await db_session.execute(
        update(OrderItem)
        .where(OrderItem.order_id == order_id)
        .values(unit_price_usd=Decimal("9.99"))
    )
    await db_session.commit()

    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()

    assert await _balance(db_session, merchant_id) == Decimal(FUNDING)
    rows = await _refund_rows(db_session, order_id)
    assert len(rows) == 1


async def test_an_order_with_no_charge_refunds_nothing_and_calls_a_human(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """Ruling 5's last clause: not an error to swallow.

    Nothing can produce this today — the debit and the order row are written
    in one transaction — so it is a bug or a hand-edited database, and the
    answer is "post nothing, tell somebody" rather than "guess an amount".
    """
    merchant_id, _key, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-nocharge"
    )
    charge = (
        await db_session.execute(
            select(WalletTransaction).where(
                WalletTransaction.idempotency_key == merchant_deposit.charge_key(order_id)
            )
        )
    ).scalar_one()
    await db_session.execute(
        update(WalletTransaction).where(WalletTransaction.id == charge.id).values(reference_id=None)
    )
    await db_session.execute(
        update(WalletTransaction)
        .where(WalletTransaction.id == charge.id)
        .values(idempotency_key=f"scrubbed-{charge.id}")
    )
    await db_session.commit()

    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()

    assert await _refund_rows(db_session, order_id) == []
    assert _merchant_alerts(alerts) == ["_alert_merchant_refund_failed"]
    task = (
        await db_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()
    await db_session.refresh(task)
    assert ff_svc.money_outcome_of(task) is MoneyOutcome.RETURNED


# ---------- SPENT and UNKNOWN pay nothing and are parked ----------


@pytest.mark.parametrize("outcome", [MoneyOutcome.SPENT, MoneyOutcome.UNKNOWN])
async def test_a_failure_that_did_not_return_our_money_refunds_nothing(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
    outcome: MoneyOutcome,
) -> None:
    """Owner's decision: refunding money we did not get back is not a safe default."""
    merchant_id, key_id, secret, order_id = await _placed(
        integration_client,
        admin_headers,
        db_session,
        merchant_order_id=f"acme-{outcome.value}",
    )
    _failing_mock(monkeypatch, outcome)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()

    assert await _balance(db_session, merchant_id) == Decimal(FUNDING) - Decimal(PRICE)
    assert await _refund_rows(db_session, order_id) == []
    # Named state a human can find: the ops alert, and the task's own verdict.
    assert _merchant_alerts(alerts) == ["_alert_merchant_needs_a_human"]
    task = (
        await db_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()
    assert ff_svc.money_outcome_of(task) is outcome

    body = (await _read_order(integration_client, key_id, secret, f"acme-{outcome.value}")).json()
    # Ruling 2: one new value, not two. "A human is deciding" keeps the word it
    # already had, so nothing a client switches on today changes meaning.
    assert body["failure_reason"] == "fulfillment_failed"
    assert body["refunded_usd"] == "0.00"


# ---------- what the reseller sees ----------


async def test_the_refund_is_visible_on_the_order_and_on_the_statement(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """Both merchant-facing surfaces, and the one value that separates them."""
    _merchant_id, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme/seen/1"
    )
    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()

    body = (await _read_order(integration_client, key_id, secret, "acme/seen/1")).json()
    assert body["refunded_usd"] == PRICE
    assert body["failure_reason"] == "fulfillment_failed_refunded"
    # Ruling 12: the order row does not move, so the reseller polls for state.
    assert body["status"] == "fulfilling"

    row = next(
        r
        for r in await _statement(integration_client, key_id, secret)
        if r["order_id"] == order_id and r["kind"] == merchant_refund.REFUND_KIND
    )
    assert row["amount_usd"] == PRICE  # signed: positive is money coming back
    assert row["merchant_order_id"] == "acme/seen/1"


async def test_a_failed_refund_leaves_the_order_saying_a_human_is_deciding(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """``failure_reason`` is derived from the ledger, so it cannot claim a
    refund that did not post."""
    _merchant_id, key_id, secret, _order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-norefund"
    )

    async def _refuse(*_args: object, **_kwargs: object) -> WalletTransaction:
        raise merchant_refund.RefundError("nope")

    monkeypatch.setattr(merchant_refund, "refund_order", _refuse)
    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()

    body = (await _read_order(integration_client, key_id, secret, "acme-norefund")).json()
    assert body["failure_reason"] == "fulfillment_failed"
    assert body["refunded_usd"] == "0.00"


# ---------- ruling 4: a refund that fails must not poison the outcome ----------


async def test_a_refund_failure_leaves_the_task_refundable(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """``record_money_outcome`` never moves down the ladder and there is no
    operator re-grade path, so a refund crash that reached the drain's crash
    arm would convert a refundable failure into a permanently unrefundable
    one."""
    _merchant_id, _key, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-poison"
    )

    async def _refuse(*_args: object, **_kwargs: object) -> WalletTransaction:
        raise merchant_refund.RefundError("the ledger said no")

    monkeypatch.setattr(merchant_refund, "refund_order", _refuse)
    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()

    task = (
        await db_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()
    await db_session.refresh(task)
    assert task.status == "failed"
    assert ff_svc.money_outcome_of(task) is MoneyOutcome.RETURNED
    assert await _refund_rows(db_session, order_id) == []
    assert _merchant_alerts(alerts) == ["_alert_merchant_refund_failed"]


async def test_an_unexpected_refund_crash_never_reaches_the_unknown_crash_arm(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """The placement proof for ruling 4, and the queue's own survival.

    ``drain_pending_tasks``' crash arm answers an unexpected exception with
    ``UNKNOWN`` — the one value that can never be cleared. The seam therefore
    runs **outside** the savepoint that arm rolls back, which is what makes it
    safe to catch here: a catch at the seam cannot reach that arm, so the
    outcome survives whatever the refund does.

    Catching is not optional. A deterministic crash that propagated would roll
    back the batch, return the task to ``pending``, and be re-run and re-crash
    every tick — the livelock ``drain_pending_tasks``' own docstring names as
    the entire reason its savepoint exists — taking every other order's
    completed work with it. Money-safe and a total queue outage.

    So: the drain returns normally, the task still reads ``RETURNED``, nothing
    was refunded, and an operator was told.
    """
    _merchant_id, _key, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-crash"
    )

    async def _boom(*_args: object, **_kwargs: object) -> WalletTransaction:
        raise RuntimeError("an import that circled back")

    monkeypatch.setattr(merchant_refund, "refund_order", _boom)
    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)

    assert await ff_svc.drain_pending_tasks(db_session) == 1
    await db_session.commit()

    task = (
        await db_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()
    await db_session.refresh(task)
    assert task.status == "failed"
    assert ff_svc.money_outcome_of(task) is MoneyOutcome.RETURNED  # never UNKNOWN
    assert await _refund_rows(db_session, order_id) == []
    assert _merchant_alerts(alerts) == ["_alert_merchant_refund_failed"]


async def test_a_crashing_refund_does_not_take_the_rest_of_the_batch_down(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """The other half: one poisoned refund must not stall the queue.

    ``drain_pending_tasks`` is shared with every retail order. A refund that
    propagated would roll the whole batch back and re-run it next tick — for
    ever, since the crash is deterministic — so the blast radius of a bug in
    a merchant refund would be the storefront's fulfilment.
    """
    _m, _k, _s, poisoned_order = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-batch-1", n=1
    )
    retail = await _retail_order(db_session, tag="batch-healthy")
    from yupay.core.config import Settings, get_settings

    cfg = Settings(**{**get_settings().model_dump(), "fulfilment_async": True})
    await ff_svc.start_for_order(db_session, order_id=retail.id, settings=cfg)
    await db_session.commit()

    async def _boom(*_args: object, **_kwargs: object) -> WalletTransaction:
        raise RuntimeError("an import that circled back")

    monkeypatch.setattr(merchant_refund, "refund_order", _boom)
    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)

    assert await ff_svc.drain_pending_tasks(db_session) == 2
    await db_session.commit()

    for order_id in (poisoned_order, retail.id):
        task = (
            await db_session.execute(
                select(FulfillmentTask).where(FulfillmentTask.order_id == order_id)
            )
        ).scalar_one()
        await db_session.refresh(task)
        # Both claimed, both attempted, neither left ``pending`` for the next
        # tick to re-run — which is what a propagating refund would produce.
        assert task.status == "failed"


# ---------- idempotency: re-drive, retry, concurrent drain ----------


async def test_a_re_driven_fulfilment_refunds_once(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """The reconcile sweep and the webhook route both re-enter the seam."""
    merchant_id, _key, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-redrive"
    )
    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    first = (await _refund_rows(db_session, order_id))[0].id
    again = await merchant_refund.refund_order(db_session, order=order, reason="re-drive")
    await db_session.commit()

    assert again.id == first
    assert len(await _refund_rows(db_session, order_id)) == 1
    assert await _balance(db_session, merchant_id) == Decimal(FUNDING)


async def test_an_admin_retry_after_a_refund_cannot_deliver_free_goods(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """Ruling 3, walked end to end.

    ``charge_deposit`` is idempotent on ``merchant-order:{order_id}``, so a
    second charge for one order **replays and debits nothing**. Refund, then
    Retry, then a success, and the reseller holds the goods and their money.
    """
    merchant_id, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-retry"
    )
    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()
    assert await _balance(db_session, merchant_id) == Decimal(FUNDING)

    task_id = (
        await db_session.execute(
            select(FulfillmentTask.id).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()
    # The retry that would have succeeded: the supplier is healthy again.
    monkeypatch.undo()
    with pytest.raises(ConflictError) as refusal:
        await ff_svc.retry_task(db_session, task_id=task_id)
    await db_session.rollback()
    assert refusal.value.extra.get("code") == merchant_refund.CODE_DEPOSIT_ALREADY_RETURNED

    # The ledger balances: one credit in, one charge out, one refund back.
    assert await _balance(db_session, merchant_id) == Decimal(FUNDING)
    assert len(await _refund_rows(db_session, order_id)) == 1
    body = (await _read_order(integration_client, key_id, secret, "acme-retry")).json()
    assert body["delivery"] is None
    assert body["status"] != "delivered"


async def test_a_force_complete_after_a_refund_is_refused_too(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """The same loophole through the other admin button.

    ``complete_manual_task(force=True)`` accepts any supplier's ``failed``
    task — it is the operator's escape hatch after a supplier rejection — and
    hands the goods over without touching the ledger.
    """
    _merchant_id, _key, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-force"
    )
    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()

    task_id = (
        await db_session.execute(
            select(FulfillmentTask.id).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()
    with pytest.raises(ConflictError) as refusal:
        await ff_svc.complete_manual_task(
            db_session,
            task_id=task_id,
            artifact_kind="voucher_code",
            artifact={"code": "FREE-GOODS"},
            channel="in_app",
            admin_note=None,
            admin_id="admin:1",
            force=True,
        )
    await db_session.rollback()
    assert refusal.value.extra.get("code") == merchant_refund.CODE_DEPOSIT_ALREADY_RETURNED


async def test_two_drainers_on_two_connections_refund_once(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    second_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """A real interleave over the ledger's unique index, not two coroutines
    sharing one transaction.

    The second session's posting is issued while the first's is uncommitted,
    so it blocks on ``wallet_transactions.idempotency_key`` and resolves
    through ``post()``'s IntegrityError replay once the first commits. That is
    the path a second worker replica actually takes.
    """
    merchant_id, _key, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-race"
    )
    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)  # deliberately not committed yet

    order = (await second_session.execute(select(Order).where(Order.id == order_id))).scalar_one()

    async def _second() -> str:
        txn = await merchant_refund.refund_order(second_session, order=order, reason="race")
        await second_session.commit()
        return txn.id

    racer = asyncio.create_task(_second())
    await asyncio.sleep(0.3)  # let it reach the blocking INSERT
    await db_session.commit()
    second_id = await racer

    rows = await _refund_rows(db_session, order_id)
    assert len(rows) == 1
    assert second_id == rows[0].id
    assert await _balance(db_session, merchant_id) == Decimal(FUNDING)


# ---------- what the reseller is told, and how ----------


HOOK_URL = "https://hooks.reseller.example/yupay"


async def _set_hook(client: AsyncClient, headers: dict[str, str], merchant_id: str) -> None:
    r = await client.put(
        f"/api/v1/admin/merchants/{merchant_id}/webhook",
        headers=headers,
        json={"url": HOOK_URL},
    )
    assert r.status_code == 200, r.text


async def test_the_refund_announces_the_money_by_push(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """Ruling 12, answered on both halves.

    ``order.status_changed`` does **not** fire — a terminal fulfilment failure
    moves the task, not ``orders.status``, so the order sits at ``fulfilling``
    and the seam is never reached. ``balance.credited`` does, because the hand
    settlement this replaces already emits it and an automatic path that went
    silent would remove a notification integrators get today.

    The key set is asserted exactly, in this file's own suite because the
    refund is its producer; see ``test_merchant_webhook_events.py`` for why
    exactness rather than absence is the assertion webhook payloads get.
    """
    merchant_id, _key, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-push"
    )
    await _set_hook(integration_client, admin_headers, merchant_id)

    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()

    rows = list(
        (
            await db_session.execute(
                select(MerchantWebhookDelivery)
                .where(MerchantWebhookDelivery.merchant_id == merchant_id)
                .order_by(MerchantWebhookDelivery.created_at, MerchantWebhookDelivery.id)
            )
        )
        .scalars()
        .all()
    )
    assert [row.event_type for row in rows] == ["balance.credited"]
    assert rows[0].payload == {"amount_usd": PRICE, "balance_usd": FUNDING}

    # A replay books nothing, so it announces nothing — the rule
    # ``credit_deposit`` already follows, and the reason it exists: a reseller
    # told twice credits their own customer twice.
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    await merchant_refund.refund_order(db_session, order=order, reason="replay")
    await db_session.commit()
    again = (
        await db_session.execute(
            select(func.count())
            .select_from(MerchantWebhookDelivery)
            .where(MerchantWebhookDelivery.merchant_id == merchant_id)
        )
    ).scalar_one()
    assert again == 1


async def test_a_low_balance_stall_is_not_refunded_on_an_earlier_verdict(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """``money_outcome`` outlives the attempt that wrote it, and the stall
    records none — so a stalled retry arrives here carrying the *previous*
    attempt's ``RETURNED``.

    Refunding then returns the money for an order we are about to deliver, and
    publishes ``refunded_usd`` against a ``failure_reason`` of ``null``, which
    is incoherent to a reseller. The gate is the **item's** state, the same
    line the storefront and ``_failure_reason`` already draw.
    """
    merchant_id, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-stall"
    )

    async def _refuse(*_args: object, **_kwargs: object) -> WalletTransaction:
        raise merchant_refund.RefundError("the ledger said no")

    monkeypatch.setattr(merchant_refund, "refund_order", _refuse)
    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()
    assert await _refund_rows(db_session, order_id) == []

    # The refund works again, and the retry stalls on OUR supplier balance —
    # a "failed" task whose item stays in_progress and which records no money
    # outcome of its own.
    monkeypatch.undo()
    _failing_mock(monkeypatch, None, error="supplier_low_balance")
    task_id = (
        await db_session.execute(
            select(FulfillmentTask.id).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()
    await ff_svc.retry_task(db_session, task_id=task_id)
    await db_session.commit()

    task = await db_session.get(FulfillmentTask, task_id)
    assert task is not None
    await db_session.refresh(task)
    assert task.status == "failed"
    assert ff_svc.money_outcome_of(task) is MoneyOutcome.RETURNED  # the old verdict
    assert await _refund_rows(db_session, order_id) == []
    assert await _balance(db_session, merchant_id) == Decimal(FUNDING) - Decimal(PRICE)
    body = (await _read_order(integration_client, key_id, secret, "acme-stall")).json()
    assert body["failure_reason"] is None  # the storefront-hidden stall
    assert body["refunded_usd"] == "0.00"


async def test_a_partial_settlement_does_not_claim_the_order_was_refunded(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """One cent back is not "we have already put what you paid back".

    The value reads a **sum**, and a sum is not a flag. A $0.01 attributed
    credit is permitted (the cap only stops going *past* the charge) and it
    also makes the automatic refund refuse for ever — ``already > 0``. So the
    order that most needs a human would be the one telling the reseller
    "nothing to chase, refund your customer", against $0.01 received.

    The refusal is right and stays; the **label** was the lie. Completeness is
    measured against what the order was charged — the same authority the
    refund reads its amount from.
    """
    merchant_id, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-partial"
    )
    assert (
        await _credit(integration_client, admin_headers, merchant_id, "0.01", order_id=order_id)
    ).status_code == 201

    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()

    assert await _refund_rows(db_session, order_id) == []
    assert _merchant_alerts(alerts) == ["_alert_merchant_refund_failed"]
    body = (await _read_order(integration_client, key_id, secret, "acme-partial")).json()
    assert body["refunded_usd"] == "0.01"
    assert body["failure_reason"] == "fulfillment_failed"


# ---------- the other two terminal states ----------


async def test_a_manually_failed_merchant_order_reaches_the_seam(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    alerts: list[Alert],
) -> None:
    """``fail_manual_task`` is the fourth terminal site, and it is reachable.

    A B2B-visible SKU with no sourcing rule routes to ``manual``, so an
    operator rejecting one of those ends a merchant order with the deposit
    debited. Its ``UNKNOWN`` refunds nothing — that is correct and unchanged —
    but the seam is what makes the parked deposit visible instead of a trap
    that depends on ``UNKNOWN`` never becoming refundable.
    """
    merchant_id, key_id, secret, order_id = await _placed(
        integration_client,
        admin_headers,
        db_session,
        merchant_order_id="acme-manual",
        route="manual",
    )
    assert await ff_svc.drain_pending_tasks(db_session) == 1
    await db_session.commit()
    task_id = (
        await db_session.execute(
            select(FulfillmentTask.id).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()

    await ff_svc.fail_manual_task(
        db_session,
        task_id=task_id,
        reason="account suspended",
        admin_note=None,
        admin_id="admin:1",
    )
    await db_session.commit()

    assert _merchant_alerts(alerts) == ["_alert_merchant_needs_a_human"]
    assert await _refund_rows(db_session, order_id) == []
    assert await _balance(db_session, merchant_id) == Decimal(FUNDING) - Decimal(PRICE)
    body = (await _read_order(integration_client, key_id, secret, "acme-manual")).json()
    assert body["failure_reason"] == "fulfillment_failed"


async def test_cancelling_a_merchant_task_says_the_deposit_is_parked(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    alerts: list[Alert],
) -> None:
    """Cancellation is a money state nothing else names.

    ``_apply_cancel`` sets the item ``failed`` and records **no** money
    outcome, so no refund fires and no alert would — while ``retry_task`` and
    ``complete_manual_task`` both refuse a ``cancelled`` task afterwards. The
    deposit is parked against an order nothing can move again. Refunding it
    automatically is a human's call and out of scope; being able to find it is
    not optional.
    """
    merchant_id, _key, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-cancelled"
    )
    task_id = (
        await db_session.execute(
            select(FulfillmentTask.id).where(FulfillmentTask.order_id == order_id)
        )
    ).scalar_one()

    await ff_svc.cancel_task(db_session, task_id=task_id)
    await db_session.commit()

    assert _merchant_alerts(alerts) == ["_alert_merchant_order_cancelled"]
    assert await _refund_rows(db_session, order_id) == []
    assert await _balance(db_session, merchant_id) == Decimal(FUNDING) - Decimal(PRICE)


# ---------- a hand settlement and the automatic one must not stack ----------


async def test_an_order_support_already_settled_is_not_refunded_again(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """The two paths live in different key namespaces, so ``post()`` cannot
    dedupe them for us: an operator settling at 10:00 and the drain running at
    10:05 would credit one order's deposit twice, and ``refunded_usd`` would
    publish ``2.14`` on a ``1.07`` order."""
    merchant_id, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-settled"
    )
    assert (
        await _credit(integration_client, admin_headers, merchant_id, PRICE, order_id=order_id)
    ).status_code == 201

    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()

    assert await _refund_rows(db_session, order_id) == []
    assert _merchant_alerts(alerts) == ["_alert_merchant_refund_failed"]
    body = (await _read_order(integration_client, key_id, secret, "acme-settled")).json()
    assert body["refunded_usd"] == PRICE


async def test_a_hand_credit_cannot_take_an_order_past_what_it_charged(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """The other order of the same double settlement.

    After M3b most failures settle themselves, so an operator reaching for the
    credit form is the one more likely to be acting on stale information.
    ``refunded_usd`` is documented as "how much of ``price_usd`` came back";
    the cap is what makes that sentence true.
    """
    merchant_id, _key, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-cap"
    )
    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()

    r = await _credit(integration_client, admin_headers, merchant_id, PRICE, order_id=order_id)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == merchant_deposit.CODE_ORDER_ALREADY_SETTLED
    # Unattributed goodwill is still allowed — the cap is about one order's
    # published number, not about what support may credit.
    assert (await _credit(integration_client, admin_headers, merchant_id, PRICE)).status_code == 201


async def test_the_cap_does_not_break_the_operators_own_retry(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    alerts: list[Alert],
) -> None:
    """A settlement retried under its own key still replays, not ``409``.

    The cap counts money this key may already have moved, so running it on a
    replay would answer ``409`` to the operator's own timeout retry and turn
    the endpoint's idempotency off — the one thing its ``Idempotency-Key``
    header is required for.
    """
    merchant_id, _key, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-replay-cap"
    )
    key = f"settle-{new_id()}"
    first = await _credit(
        integration_client, admin_headers, merchant_id, PRICE, order_id=order_id, key=key
    )
    assert first.status_code == 201, first.text
    second = await _credit(
        integration_client, admin_headers, merchant_id, PRICE, order_id=order_id, key=key
    )
    assert second.status_code == 201, second.text
    assert second.json()["transaction_id"] == first.json()["transaction_id"]


# ---------- a frozen merchant is still owed their money ----------


async def test_a_frozen_merchant_is_still_refunded(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """Freezing stops new orders; it does not cancel money we owe for goods we
    failed to deliver."""
    merchant_id, _key, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-frozen"
    )
    r = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/freeze",
        headers={**admin_headers, "Idempotency-Key": f"freeze-{new_id()}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "frozen"

    _failing_mock(monkeypatch, MoneyOutcome.RETURNED)
    await ff_svc.drain_pending_tasks(db_session)
    await db_session.commit()

    assert len(await _refund_rows(db_session, order_id)) == 1
    assert await _balance(db_session, merchant_id) == Decimal(FUNDING)


# ---------- retail is byte-identical ----------


async def _retail_order(db: AsyncSession, *, tag: str) -> Order:
    """A paid storefront order on a SKU pinned to the empty warehouse.

    ``force_inventory`` + no stock is the most common terminal failure in the
    codebase, and ``INVENTORY_FAILURE_MONEY_OUTCOME`` is ``RETURNED`` — so it
    is exactly the shape that would start posting merchant refunds if the
    ``merchant_id`` gate were dropped.
    """
    user_id = new_id()
    db.add(User(id=user_id, email=f"retail-{tag}@example.com", locale="ru", roles=[]))
    await db.flush()
    sku_id = await _seed_sku(db, n=9, route="inventory")
    order = Order(
        id=new_id(),
        user_id=user_id,
        status="paid",
        currency="USD",
        total_usd=Decimal("1.00"),
        total_charged=Decimal("1.00"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderItem(
            id=new_id(),
            order_id=order.id,
            sku_id=sku_id,
            qty=1,
            unit_price_usd=Decimal("1.00"),
        )
    )
    await db.commit()
    return order


async def test_a_retail_failure_never_reaches_the_refund_at_all(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[Alert],
) -> None:
    """Ruling 7. Delete the ``order.merchant_id is not None`` gate and the spy
    below records a call."""
    from yupay.core.config import Settings, get_settings

    order = await _retail_order(db_session, tag="gate")
    calls: list[str] = []

    async def _spy(db: AsyncSession, *, order: Order, reason: str) -> None:
        calls.append(order.id)

    monkeypatch.setattr(merchant_refund, "refund_order", _spy)
    cfg = Settings(**{**get_settings().model_dump(), "fulfilment_async": True})
    await ff_svc.start_for_order(db_session, order_id=order.id, settings=cfg)
    await db_session.commit()

    assert await ff_svc.drain_pending_tasks(db_session) == 1
    await db_session.commit()

    assert calls == []
    assert _merchant_alerts(alerts) == []
    task = (
        await db_session.execute(
            select(FulfillmentTask).where(FulfillmentTask.order_id == order.id)
        )
    ).scalar_one()
    await db_session.refresh(task)
    assert task.status == "failed"
    assert ff_svc.money_outcome_of(task) is MoneyOutcome.RETURNED
    item = (
        await db_session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    ).scalar_one()
    await db_session.refresh(item)
    assert item.fulfillment_state == "failed"
    # And no money moved anywhere: a retail buyer's money is at an acquirer.
    assert (
        await db_session.execute(select(func.count()).select_from(WalletTransaction))
    ).scalar_one() == 0
