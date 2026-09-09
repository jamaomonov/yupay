"""A stalled merchant order says it is stalled (Merchant B2B M3b, Task 4).

When a supplier refuses because **our** balance with them is too low, the
fulfilment task fails into the admin inbox but the order item deliberately
stays ``in_progress`` — retail's rule, so a storefront buyer sees "обработка"
rather than an error for something an operator fixes in minutes. A reseller
reading ``GET /merchant/v1/orders/{merchant_order_id}`` saw
``status: "fulfilling", failure_reason: null`` — byte-identical to an order
placed thirty seconds ago, for ever.

This file is organised around the two halves of that fix:

* **the value appears, and never says why.** ``fulfillment_delayed`` is
  non-terminal: the order is still coming. What *caused* it — that we ran out
  of balance at a named supplier — is our supplier relationship, not the
  reseller's order, and stays on the task, in the admin inbox and in the ops
  alert.
* **the value goes away again, on every edge.** A stall that never clears is
  worse than one that is invisible, because a machine acts on it. The
  transition table below is walked one test per row: a top-up and a successful
  retry, a retry that fails terminally with and without our money back, a
  cancellation, support closing the order by hand, an operator delivering it
  manually, and a second stall.

**Retail is proved unchanged by construction, not by assertion.** A buyer must
not be able to tell a stalled order from a busy one, so the storefront body of
a stalled order is compared against the storefront body of an order that is
genuinely mid-flight — the same fields, byte for byte, once the ids and
timestamps that differ between any two orders are normalised away. Delete
``_apply_failure``'s low-balance early return and that comparison fails, which
is the only version of "retail is unchanged" worth writing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.config import Settings, get_settings
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
from yupay.modules.fulfillment import stall as ff_stall
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers import FulfillResult, MoneyOutcome
from yupay.modules.fulfillment.suppliers.mock import MockFulfiller
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.sourcing.models import SkuSourcingRule
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
ORDERS_PATH = "/merchant/v1/orders"

#: Cost $1.00 at 7 % markup — what every merchant order below is charged.
PRICE = "1.07"
#: What the deposit is funded with before each order.
FUNDING = "10.00"

#: The sentinel ``fulfillment`` keys on to tell a stall from a real failure.
#: Spelled out rather than imported: this is the string an adapter writes, and
#: a test that imports the constant it is pinning proves only consistency.
LOW_BALANCE = "supplier_low_balance"

#: What the reseller must never be able to read off the API. The cause is a
#: fact about our supplier funding, and a reseller who could see it would learn
#: which of our suppliers is short of money.
FORBIDDEN_IN_A_STALL_BODY = ("low_balance", "balance", "supplier", "g2b", "waxpeer", "mock")


# ---------- harness ----------


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login(client: AsyncClient, tg_id: int, name: str = "U") -> str:
    user_json = json.dumps({"id": tg_id, "first_name": name}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token: str = r.json()["access_token"]
    return token


async def _user_id_of(db: AsyncSession, tg_id: int) -> str:
    user_id: str = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    return user_id


@pytest.fixture
async def admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    """Log a Telegram user in and grant it the admin role."""
    token = await _login(integration_client, 61, "Admin")
    user_id = await _user_id_of(db_session, 61)
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Swallow every ops alert the saga dispatches.

    ``_dispatch_alert`` is handed a live coroutine; letting it reach
    ``asyncio.create_task`` leaves un-awaited work running past the test. The
    alert *content* is Task 3's subject and is asserted there — here they are
    noise, and the point is only that the reseller-facing value does not
    depend on one.
    """
    captured: list[object] = []

    def _capture(coro: Any) -> None:
        coro.close()
        captured.append(coro.cr_code.co_name)

    monkeypatch.setattr(ff_svc, "_dispatch_alert", _capture)
    return captured


@pytest.fixture
async def sql_counter(db_engine) -> AsyncIterator[dict[str, int]]:  # type: ignore[no-untyped-def]  # conftest fixture is untyped
    """Counts every cursor execution on the engine the app is wired to."""
    from sqlalchemy import event

    holder = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany) -> None:  # type: ignore[no-untyped-def]  # SQLAlchemy event signature
        holder["n"] += 1

    sync_engine = db_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        yield holder
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)


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
    key_id: str = payload["key_id"]
    secret: str = payload["secret"]
    return key_id, secret


async def _credit(
    client: AsyncClient, headers: dict[str, str], merchant_id: str, amount: str
) -> None:
    r = await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/deposit-credits",
        headers={**headers, "Idempotency-Key": f"credit-{new_id()}"},
        json={"amount": amount},
    )
    assert r.status_code == 201, r.text


def _signed(
    key_id: str, secret: str, *, method: str, path: str, query: str = "", body: bytes = b""
) -> dict[str, str]:
    """The three auth headers, transcribed from the module README by hand."""
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


async def _read(client: AsyncClient, key_id: str, secret: str, merchant_order_id: str) -> Response:
    path = f"{ORDERS_PATH}/{quote(merchant_order_id, safe='')}"
    return await client.get(path, headers=_signed(key_id, secret, method="GET", path=path))


# ---------- seeding ----------


async def _seed_sku(db: AsyncSession, *, n: int, route: str = "mock") -> str:
    """A B2B-visible SKU at $1.00 cost / 7 % markup, pinned to one route."""
    suffix = new_id()[-8:]
    category = Category(
        id=new_id(),
        slug=f"cat-{n}-{suffix}",
        sort_order=n,
        active=True,
        translations=[CategoryTranslation(locale="ru", name=f"Категория {n}")],
    )
    brand = Brand(
        id=new_id(),
        slug=f"brand-{n}-{suffix}",
        category_id=category.id,
        sort_order=n,
        active=True,
        visible_b2b=True,
        translations=[BrandTranslation(locale="ru", name=f"Бренд {n}")],
    )
    product = Product(
        id=new_id(),
        slug=f"product-{n}-{suffix}",
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
        sku_code=f"sku-{n}-{suffix}",
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
    await db.flush()
    db.add(
        SkuSourcingRule(
            sku_id=sku.id,
            mode="force_inventory" if route == "inventory" else "force_supplier",
            supplier_slug=None if route == "inventory" else route,
        )
    )
    await db.flush()
    return sku.id


async def _placed(
    client: AsyncClient,
    headers: dict[str, str],
    db: AsyncSession,
    *,
    merchant_order_id: str,
    n: int = 1,
) -> tuple[str, str, str, str]:
    """A merchant, a key, a funded deposit and one placed order.

    Returns ``(merchant_id, key_id, secret, order_id)``. The task is left
    ``pending`` — the merchant path is enqueue-only by construction — so each
    test drives it with whatever the row it is about needs.
    """
    merchant_id = await _new_merchant(client, headers, title=f"Reseller {n}")
    key_id, secret = await _new_key(client, headers, merchant_id)
    await _credit(client, headers, merchant_id, FUNDING)
    sku_id = await _seed_sku(db, n=n)
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


def _mock_returns(
    monkeypatch: pytest.MonkeyPatch,
    result: FulfillResult,
) -> None:
    """Make every mock fulfilment answer with exactly this result."""

    async def _answer(
        self: MockFulfiller,
        *,
        db: AsyncSession,
        order: Order,
        item: OrderItem,
        idempotency_key: str,
    ) -> FulfillResult:
        return result

    monkeypatch.setattr(MockFulfiller, "fulfill", _answer)


def _stall() -> FulfillResult:
    """What an adapter returns when **our** balance at the supplier is short.

    ``money_outcome=None`` is the whole difference from a terminal failure: no
    supplier call has finished happening to our money, so there is nothing to
    classify (M3b Task 1 makes that a defaultless required field, and the
    stall is the one exit allowed to answer ``None``).
    """
    return FulfillResult(
        outcome="failed",
        external_order_id=None,
        artifact_kind=None,
        artifact=None,
        error=LOW_BALANCE,
        extra_metadata={"supplier": "mock", "low_balance": True, "current_balance": "0.50"},
        money_outcome=None,
    )


def _terminal(outcome: MoneyOutcome) -> FulfillResult:
    return FulfillResult(
        outcome="failed",
        external_order_id=None,
        artifact_kind=None,
        artifact=None,
        error="supplier refused",
        extra_metadata={},
        money_outcome=outcome,
    )


def _delivered() -> FulfillResult:
    return FulfillResult(
        outcome="succeeded",
        external_order_id="ext-1",
        artifact_kind="voucher_code",
        artifact={"code": "WXYZ-1234-ABCD"},
        error=None,
        extra_metadata={},
        money_outcome=None,
    )


def _in_progress() -> FulfillResult:
    return FulfillResult(
        outcome="in_progress",
        external_order_id="ext-2",
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata={},
        money_outcome=None,
    )


async def _reload_order(db: AsyncSession, order_id: str) -> Order:
    """The order with fresh items, after work committed on another path."""
    db.expire_all()
    order: Order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one()
    return order


async def _task_id(db: AsyncSession, order_id: str) -> str:
    task_id: str = (
        await db.execute(select(FulfillmentTask.id).where(FulfillmentTask.order_id == order_id))
    ).scalar_one()
    return task_id


async def _drain_into_the_stall(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, order_id: str
) -> None:
    """Run the real drain once, with a supplier that is short of our money."""
    _mock_returns(monkeypatch, _stall())
    assert await ff_svc.drain_pending_tasks(db) == 1
    await db.commit()
    task = (
        await db.execute(select(FulfillmentTask).where(FulfillmentTask.order_id == order_id))
    ).scalar_one()
    await db.refresh(task)
    assert task.status == "failed"
    assert task.last_error == LOW_BALANCE


# ---------- the value appears ----------


async def test_a_supplier_low_balance_stall_says_the_order_is_delayed(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """The whole task: an order that has stopped moving says so, and stays open.

    ``status`` is deliberately still ``fulfilling`` — nothing advanced the
    order row and nothing should, because the order is still coming. The
    reseller's machine now has a third answer between "in flight" and
    "terminally failed".
    """
    _merchant, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-delayed"
    )
    await _drain_into_the_stall(db_session, monkeypatch, order_id)

    body = (await _read(integration_client, key_id, secret, "acme-delayed")).json()

    assert body["failure_reason"] == "fulfillment_delayed"
    assert body["status"] == "fulfilling"
    assert body["delivery"] is None
    assert body["refunded_usd"] == "0.00"


async def test_the_stall_never_says_why_it_stalled(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """The cause is *our* supplier funding, and it stays ours.

    A reseller who could read "we ran out of balance at G2B" off this endpoint
    would learn which of our suppliers is short of money — the same class of
    leak that keeps ``SPENT`` and ``UNKNOWN`` out of ``failure_reason``. The
    distinction lives on the task, in the admin inbox and in the low-balance
    ops alert, which is where the person who acts on it looks.
    """
    _merchant, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-why"
    )
    await _drain_into_the_stall(db_session, monkeypatch, order_id)

    raw = (await _read(integration_client, key_id, secret, "acme-why")).text

    assert "fulfillment_delayed" in raw
    for forbidden in FORBIDDEN_IN_A_STALL_BODY:
        assert forbidden not in raw.lower(), forbidden


async def test_an_order_still_in_flight_is_not_delayed(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """The value must not degenerate into "``fulfilling`` for a while".

    An order whose supplier call is still open is exactly what the reseller
    should keep waiting on without escalating, and it is the state a stall is
    indistinguishable from today. If this ever goes non-null, the field has
    stopped carrying information.
    """
    _merchant, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-inflight"
    )
    fresh = (await _read(integration_client, key_id, secret, "acme-inflight")).json()
    assert fresh["failure_reason"] is None

    _mock_returns(monkeypatch, _in_progress())
    assert await ff_svc.drain_pending_tasks(db_session) == 1
    await db_session.commit()

    body = (await _read(integration_client, key_id, secret, "acme-inflight")).json()
    assert body["failure_reason"] is None
    assert body["status"] == "fulfilling"


# ---------- the value goes away again ----------


async def test_a_top_up_and_a_successful_retry_clear_the_stall(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """The ordinary ending: an operator tops the supplier up and clicks Retry."""
    _merchant, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-toppedup"
    )
    await _drain_into_the_stall(db_session, monkeypatch, order_id)
    assert (await _read(integration_client, key_id, secret, "acme-toppedup")).json()[
        "failure_reason"
    ] == "fulfillment_delayed"

    monkeypatch.undo()
    _mock_returns(monkeypatch, _delivered())
    await ff_svc.retry_task(db_session, task_id=await _task_id(db_session, order_id))
    await db_session.commit()

    body = (await _read(integration_client, key_id, secret, "acme-toppedup")).json()
    assert body["failure_reason"] is None
    assert body["status"] == "delivered"
    assert body["delivery"]["artifact"] == {"code": "WXYZ-1234-ABCD"}


async def test_a_retry_that_fails_with_our_money_back_reads_as_refunded(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """A stall that turns terminal hands over to Task 3's ledger-derived split.

    The stall records no money outcome, so the retry's ``RETURNED`` is the
    first verdict the task has ever had — the monotone ladder in
    ``record_money_outcome`` has nothing to refuse — and the automatic refund
    posts. The reseller reads the refunded value, not the delayed one.
    """
    _merchant, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-thenrefund"
    )
    await _drain_into_the_stall(db_session, monkeypatch, order_id)

    monkeypatch.undo()
    _mock_returns(monkeypatch, _terminal(MoneyOutcome.RETURNED))
    await ff_svc.retry_task(db_session, task_id=await _task_id(db_session, order_id))
    await db_session.commit()

    body = (await _read(integration_client, key_id, secret, "acme-thenrefund")).json()
    assert body["failure_reason"] == "fulfillment_failed_refunded"
    assert body["refunded_usd"] == PRICE
    # M3c Task 6: ``retry_task`` is one of the four sites that reach the refund
    # seam, so a stall that ends in a full refund closes the order here too.
    # The value read back is still the refunded one and not ``order_failed``,
    # which is the precedence that had to be corrected in the same commit.
    assert body["status"] == "failed"


async def test_a_retry_that_fails_without_our_money_reads_as_a_human_deciding(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """The other terminal ending, and the one the stall must not soften.

    ``SPENT`` refunds nothing. Leaving ``fulfillment_delayed`` here would tell
    a reseller to keep waiting for an order that will never arrive — so the
    value has to be **gone**, not merely outranked. It is gone because the
    retry moved the item to ``failed``, which takes the predicate itself out;
    the ordering between the two branches is pinned in the unit table, where
    the combination can be constructed.
    """
    _merchant, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-thenspent"
    )
    await _drain_into_the_stall(db_session, monkeypatch, order_id)

    monkeypatch.undo()
    _mock_returns(monkeypatch, _terminal(MoneyOutcome.SPENT))
    await ff_svc.retry_task(db_session, task_id=await _task_id(db_session, order_id))
    await db_session.commit()

    body = (await _read(integration_client, key_id, secret, "acme-thenspent")).json()
    assert body["failure_reason"] == "fulfillment_failed"
    assert body["refunded_usd"] == "0.00"


async def test_a_second_stall_still_reads_as_delayed(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """The value is a state, not an event: a retry that stalls again still says so.

    The realistic shape of a bad hour — an operator tops up too little, or
    another order drains the balance first.
    """
    _merchant, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-restall"
    )
    await _drain_into_the_stall(db_session, monkeypatch, order_id)

    await ff_svc.retry_task(db_session, task_id=await _task_id(db_session, order_id))
    await db_session.commit()

    body = (await _read(integration_client, key_id, secret, "acme-restall")).json()
    assert body["failure_reason"] == "fulfillment_delayed"
    assert body["status"] == "fulfilling"


async def test_cancelling_a_stalled_task_replaces_the_stall_with_a_terminal_value(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """A cancelled task ends the item, so the order stops being "still coming".

    ``_apply_cancel`` writes ``fulfillment_state = "failed"`` (there is no
    ``cancelled`` value on the item), which is the same fact
    ``fulfillment_failed`` already reports. Nothing about this had to be
    taught the new value — but it is exactly the edge where a *stored* marker
    would have been left behind.
    """
    _merchant, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-cancelled"
    )
    await _drain_into_the_stall(db_session, monkeypatch, order_id)

    await ff_svc.cancel_task(db_session, task_id=await _task_id(db_session, order_id))
    await db_session.commit()

    body = (await _read(integration_client, key_id, secret, "acme-cancelled")).json()
    assert body["failure_reason"] == "fulfillment_failed"


async def test_support_closing_a_stalled_order_by_hand_wins(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """A hand closure ends the stall, and it ends it twice over.

    What this pins is the **end state**, not the precedence. Measured rather
    than assumed: ``mark_order_failed_admin`` cascades through
    ``cancel_open_tasks_for_order``, which cancels a ``failed`` task too, so by
    the time the read happens the task is ``cancelled`` and the item is
    ``failed`` — the predicate already answers no, and ``order_failed`` would
    win even if it did not. Two independent reasons, which is why moving the
    stall branch above the status check does not redden this test.

    The precedence itself is pinned where the combination can actually be
    built — ``test_the_failure_reason_table``'s "stalled and closed" row — and
    it is defence in depth: no route reachable today produces a merchant order
    that is both closed and stalled.
    """
    _merchant, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-closed"
    )
    await _drain_into_the_stall(db_session, monkeypatch, order_id)

    r = await integration_client.post(
        f"/api/v1/admin/orders/{order_id}/fail",
        headers=admin_headers,
        json={"reason": "supplier permanently out"},
    )
    assert r.status_code == 200, r.text

    body = (await _read(integration_client, key_id, secret, "acme-closed")).json()
    assert body["status"] == "failed"
    assert body["failure_reason"] == "order_failed"


async def test_delivering_a_stalled_order_by_hand_clears_it(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """The operator's other move: buy it somewhere else and force-complete.

    ``complete_manual_task`` is the documented answer to a low-balance task an
    operator does not want to wait on, and it is the second way the value has
    to disappear on its own.
    """
    _merchant, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-byhand"
    )
    await _drain_into_the_stall(db_session, monkeypatch, order_id)

    r = await integration_client.post(
        f"/api/v1/admin/fulfillment/tasks/{await _task_id(db_session, order_id)}/force-complete",
        headers=admin_headers,
        json={
            "artifact_kind": "voucher_code",
            "artifact": {"code": "HAND-0000-0000"},
            "channel": "in_app",
            "admin_note": "куплено напрямую",
        },
    )
    assert r.status_code == 200, r.text

    body = (await _read(integration_client, key_id, secret, "acme-byhand")).json()
    assert body["failure_reason"] is None
    assert body["status"] == "delivered"


async def test_a_terminal_failure_can_become_a_delay_again(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """ "Terminal" is about the delivery attempt, not about the order for ever.

    An operator may retry a ``fulfillment_failed`` order whose money never came
    back — ``_refuse_a_settled_merchant_order`` only blocks the retry once the
    deposit has gone back — and if that retry stalls, the published value goes
    ``fulfillment_failed`` → ``fulfillment_delayed``. Backwards, by the
    README's own ``Terminal?`` column.

    It is the right answer (the order really is coming again) and it is a
    promise we have not made, so the contract text now says the three terminal
    values mean "act now", not "this can never change". Written as a test
    because that is a published claim, and a published claim nobody executed
    is how the two sentences this task had to repair got written.
    """
    _merchant, key_id, secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-backwards"
    )
    _mock_returns(monkeypatch, _terminal(MoneyOutcome.SPENT))
    assert await ff_svc.drain_pending_tasks(db_session) == 1
    await db_session.commit()
    first = (await _read(integration_client, key_id, secret, "acme-backwards")).json()
    assert first["failure_reason"] == "fulfillment_failed"
    assert first["refunded_usd"] == "0.00"

    _mock_returns(monkeypatch, _stall())
    await ff_svc.retry_task(db_session, task_id=await _task_id(db_session, order_id))
    await db_session.commit()

    second = (await _read(integration_client, key_id, secret, "acme-backwards")).json()
    assert second["failure_reason"] == "fulfillment_delayed"
    assert second["status"] == "fulfilling"


# ---------- the predicate on its own terms ----------


async def test_one_merchants_stall_does_not_delay_another_merchants_order(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """The predicate is scoped to **this** order, and that is the whole ballgame.

    Every other test here builds one order in a TRUNCATE-isolated database, so
    ``FulfillmentTask.order_id == order.id`` could be deleted and nothing would
    notice. Deleting it is not a fanciful mutation: folding the filter into the
    join, or reusing this query for a "list stalled orders" admin view, gets
    there without anybody intending it.

    What it would cost is this task's own harm, inverted. One reseller running
    us out of balance at a supplier would make **every other merchant's**
    healthy in-flight order publish ``fulfillment_delayed`` — and their
    machines, which this value exists to give something to act on, would stop
    escalating on orders that are perfectly fine, indefinitely.

    So: two merchants, two orders, one stalled. The healthy one must be
    ``null``, and the stalled one must still be ``fulfillment_delayed`` — the
    second half is the control, without which this test would pass on a
    function that answers ``False`` to everything.
    """
    _m1, key_stalled, secret_stalled, stalled_order = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-noisy", n=1
    )
    await _drain_into_the_stall(db_session, monkeypatch, stalled_order)

    _m2, key_ok, secret_ok, healthy_order = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="beta-quiet", n=2
    )
    _mock_returns(monkeypatch, _in_progress())
    assert await ff_svc.drain_pending_tasks(db_session) == 1
    await db_session.commit()

    healthy = await _reload_order(db_session, healthy_order)
    assert await ff_stall.order_is_stalled(db_session, order=healthy) is False

    beta = (await _read(integration_client, key_ok, secret_ok, "beta-quiet")).json()
    assert beta["failure_reason"] is None
    assert beta["status"] == "fulfilling"

    acme = (await _read(integration_client, key_stalled, secret_stalled, "acme-noisy")).json()
    assert acme["failure_reason"] == "fulfillment_delayed"


async def test_a_terminally_failed_order_is_not_stalled(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """``order_is_stalled`` is asked directly, because it is a public predicate.

    Through ``_failure_reason`` a terminal failure never reaches the stall
    branch — the failed *item* is checked first — so the item half of the
    predicate would be invisible from the endpoint. It is not decoration: the
    predicate answers "stopped, but not finished failing" for any caller, and
    the next one will not necessarily have excluded the failed items first.
    """
    _merchant, _key_id, _secret, order_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-terminal"
    )
    order = await _reload_order(db_session, order_id)
    assert await ff_stall.order_is_stalled(db_session, order=order) is False

    _mock_returns(monkeypatch, _terminal(MoneyOutcome.SPENT))
    assert await ff_svc.drain_pending_tasks(db_session) == 1
    await db_session.commit()

    order = await _reload_order(db_session, order_id)
    assert await ff_stall.order_is_stalled(db_session, order=order) is False


async def test_a_settled_order_costs_no_stall_query(
    integration_client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
    sql_counter: dict[str, int],
) -> None:
    """This is the endpoint we tell resellers to poll, so the read pays only
    when the answer can be yes.

    Every item of a delivered order is in a terminal state, so no task of it
    can be a stalled one and the database is not asked. An open order pays one
    indexed read on ``ix_fulfillment_tasks_order_id``. The claim is the
    *difference*, not a magic number, so it survives an unrelated query
    landing on this path.
    """
    _merchant, key_id, secret, open_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-open", n=1
    )
    _m2, key2, secret2, done_id = await _placed(
        integration_client, admin_headers, db_session, merchant_order_id="acme-done", n=2
    )
    _mock_returns(monkeypatch, _delivered())
    await ff_svc.retry_task(db_session, task_id=await _task_id(db_session, done_id))
    await db_session.commit()

    # Read both once before measuring anything. The delivery above leaves
    # background work (a notification, a realtime nudge) that the event loop
    # only runs at the next await, and it lands inside whichever request comes
    # first — 11 statements of somebody else's work on the first measurement.
    assert (await _read(integration_client, key_id, secret, "acme-open")).status_code == 200
    assert (await _read(integration_client, key2, secret2, "acme-done")).status_code == 200

    sql_counter["n"] = 0
    assert (await _read(integration_client, key_id, secret, "acme-open")).status_code == 200
    cost_open = sql_counter["n"]

    sql_counter["n"] = 0
    assert (await _read(integration_client, key2, secret2, "acme-done")).status_code == 200
    cost_done = sql_counter["n"]

    assert cost_open == cost_done + 1, (cost_open, cost_done)


# ---------- retail is unchanged, and the proof reds if the gate goes ----------

#: Everything that legitimately differs between any two orders. Whatever is
#: left has to match, or a buyer can tell a stalled order from a busy one.
_PER_ORDER = ("id", "created_at", "expires_at", "paid_at", "fx_snapshot_id")


async def _retail_order(db: AsyncSession, *, user_id: str, sku_id: str, lines: int = 1) -> str:
    """A paid storefront order routed to the mock supplier.

    Both orders in the comparison below share **one** SKU: ``OrderItemOut``
    carries a ``display`` block (brand, denomination, image), so two SKUs
    would differ in ten fields that have nothing to do with the stall.

    ``lines`` is why this is a *retail* helper and not a merchant one: a
    merchant order is one SKU by construction, and the predicate's item half
    only has anything to do on an order with more than one line.
    """
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
    for _ in range(lines):
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
    return order.id


def _normalised(body: dict[str, Any]) -> dict[str, Any]:
    """The buyer's view with the per-order facts blanked out."""
    out = {k: ("<per-order>" if k in _PER_ORDER else v) for k, v in body.items()}
    out["items"] = [
        {k: ("<per-order>" if k in _PER_ORDER else v) for k, v in item.items()}
        for item in body["items"]
    ]
    return out


async def test_the_storefront_cannot_tell_a_stalled_order_from_a_busy_one(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """Retail's rule, and the reason this task is merchant-facing only.

    A buyer has a support chat and a refund button; an order an operator will
    fix in minutes is not worth showing them an error for. So the storefront
    body of a **stalled** order must equal the storefront body of one whose
    supplier call is genuinely still open — same status, same
    ``fulfillment_state``, same everything but the per-order facts.

    This is written as a comparison rather than as an assertion on two literal
    values because it has to **fail if the guarantee is removed**: delete
    ``_apply_failure``'s low-balance early return and the stalled order's item
    flips to ``failed`` while the busy one does not.
    """
    token = await _login(integration_client, 62, "Buyer")
    user_id = await _user_id_of(db_session, 62)
    sku_id = await _seed_sku(db_session, n=7)
    busy_id = await _retail_order(db_session, user_id=user_id, sku_id=sku_id)
    stalled_id = await _retail_order(db_session, user_id=user_id, sku_id=sku_id)
    enqueue = Settings(**{**get_settings().model_dump(), "fulfilment_async": True})
    for order_id in (busy_id, stalled_id):
        await ff_svc.start_for_order(db_session, order_id=order_id, settings=enqueue)
    await db_session.commit()

    _mock_returns(monkeypatch, _in_progress())
    assert await ff_svc.drain_pending_tasks(db_session) == 2
    await db_session.commit()
    monkeypatch.undo()
    _mock_returns(monkeypatch, _stall())
    task_id = await _task_id(db_session, stalled_id)
    await ff_svc.process_task(db_session, task_id=task_id)
    await db_session.commit()

    auth = {"Authorization": f"Bearer {token}"}
    busy = await integration_client.get(f"/api/v1/orders/{busy_id}", headers=auth)
    stalled = await integration_client.get(f"/api/v1/orders/{stalled_id}", headers=auth)
    assert busy.status_code == 200, busy.text
    assert stalled.status_code == 200, stalled.text

    assert _normalised(stalled.json()) == _normalised(busy.json())
    assert stalled.json()["status"] == "fulfilling"
    assert stalled.json()["items"][0]["fulfillment_state"] == "in_progress"
    # The reseller's word is merchant-facing only; it is not a field here and
    # not a value of one.
    assert "delayed" not in stalled.text


async def test_a_line_that_terminally_failed_does_not_stall_the_line_beside_it(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    alerts: list[object],
) -> None:
    """The predicate's **item** half, which nothing else in this file can reach.

    A merchant order is one SKU by construction, and on a single-line order the
    item half is redundant with the cheap precondition above it: if the only
    item is terminal there is no query, and if it is open there is only one
    task to ask about. So the mutation that deletes it stayed green until this
    test existed — the shape it is wrong about needs **two** lines.

    One line failed for good; the one beside it is mid-call. Without the item
    half the failed line's dead task answers for the whole order and a busy
    order reads as stalled. ``order_is_stalled`` is a public predicate on
    ``fulfillment.api``: it has to be right for the caller that has not
    already excluded the failed lines, not only for the one that has.
    """
    user_id = new_id()
    db_session.add(User(id=user_id, email=f"multi-{user_id}@example.com", locale="ru", roles=[]))
    await db_session.flush()
    sku_id = await _seed_sku(db_session, n=11)
    order_id = await _retail_order(db_session, user_id=user_id, sku_id=sku_id, lines=2)
    enqueue = Settings(**{**get_settings().model_dump(), "fulfilment_async": True})
    await ff_svc.start_for_order(db_session, order_id=order_id, settings=enqueue)
    await db_session.commit()

    dead, busy = sorted(
        (
            await db_session.execute(
                select(FulfillmentTask.id).where(FulfillmentTask.order_id == order_id)
            )
        )
        .scalars()
        .all()
    )
    _mock_returns(monkeypatch, _terminal(MoneyOutcome.SPENT))
    await ff_svc.process_task(db_session, task_id=dead)
    _mock_returns(monkeypatch, _in_progress())
    await ff_svc.process_task(db_session, task_id=busy)
    await db_session.commit()

    order = await _reload_order(db_session, order_id)
    assert await ff_stall.order_is_stalled(db_session, order=order) is False

    # The positive control, so the assertion above cannot be passing because
    # the function answers ``False`` to everything: stall the busy line and the
    # same order flips.
    _mock_returns(monkeypatch, _stall())
    await ff_svc.process_task(db_session, task_id=busy)
    await db_session.commit()

    order = await _reload_order(db_session, order_id)
    assert await ff_stall.order_is_stalled(db_session, order=order) is True
