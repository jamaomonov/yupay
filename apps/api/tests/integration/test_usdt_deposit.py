"""USDT (TRC20) top-up: reservations, chain intake, polling, admin and cabinet (ADR-0104)."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core.clock import now
from yupay.core.errors import AppError
from yupay.core.ids import new_id
from yupay.modules.merchants.deposit import deposit_balance
from yupay.modules.usdt import intake, poll, reservations
from yupay.modules.usdt.address import is_tron_address
from yupay.modules.usdt.models import UsdtIncoming, UsdtReservation
from yupay.modules.usdt.settings import load_settings
from yupay.modules.usdt.tron import USDT_CONTRACT, Transfer, parse_transfer

from tests.integration.cabinet_signup import BASE
from tests.integration.cabinet_signup import auth as _auth
from tests.integration.cabinet_signup import signed_up as _signed_up
from tests.integration.p2p_fixtures import _code, _merchant

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _tron(seed: int) -> str:
    """A valid mainnet TRON address made from ``seed`` (base58check, prefix 0x41)."""
    payload = b"\x41" + hashlib.sha256(str(seed).encode()).digest()[:20]
    raw = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    num = int.from_bytes(raw, "big")
    out = ""
    while num:
        num, rem = divmod(num, 58)
        out = _B58[rem] + out
    return out


OURS = _tron(1)
PAYER = _tron(2)


async def _open(db: AsyncSession, merchant_ids: list[str]) -> None:
    s = await load_settings(db)
    s.mode, s.allowlist_merchant_ids, s.address = "allowlist", merchant_ids, OURS
    s.cursor_block_ms = int((now() - timedelta(hours=1)).timestamp() * 1000)
    await db.flush()


def _transfer(
    amount: str, *, at_offset: timedelta = timedelta(0), tx: str | None = None
) -> Transfer:
    at = now() + at_offset
    return Transfer(
        tx_id=tx or hashlib.sha256(new_id().encode()).hexdigest(),
        from_address=PAYER,
        to_address=OURS,
        amount=Decimal(amount),
        block_at=at,
        block_ms=int(at.timestamp() * 1000),
    )


def _row(amount_units: str, **over: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "transaction_id": "ab" * 32,
        "token_info": {"address": USDT_CONTRACT, "decimals": 6, "symbol": "USDT"},
        "block_timestamp": int(now().timestamp() * 1000),
        "from": PAYER,
        "to": OURS,
        "type": "Transfer",
        "value": amount_units,
    }
    item.update(over)
    return item


# --- address & parsing -------------------------------------------------------


def test_address_check_accepts_real_and_refuses_typos() -> None:
    assert is_tron_address(USDT_CONTRACT)
    assert is_tron_address(OURS)
    assert not is_tron_address(OURS[:-1] + ("A" if OURS[-1] != "A" else "B"))
    assert not is_tron_address("0x2C77989B3b7C6bA635BCB366D89480c4422756E4")
    assert not is_tron_address("")


def test_parse_keeps_only_real_usdt_to_us() -> None:
    good = parse_transfer(_row("100000000"), OURS)
    assert good is not None
    assert good.amount == Decimal("100")
    fake = _row("100000000", token_info={"address": _tron(9), "decimals": 6, "symbol": "USDT"})
    assert parse_transfer(fake, OURS) is None
    assert parse_transfer(_row("100000000", to=_tron(3)), OURS) is None
    assert parse_transfer(_row("100000000", type="Approval"), OURS) is None
    assert parse_transfer(_row("1e9"), OURS) is None
    assert parse_transfer(_row("100", block_timestamp=True), OURS) is None


# --- reservations ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_taken_amount_bumps_by_a_cent(db_session: AsyncSession) -> None:
    a, b = await _merchant(db_session), await _merchant(db_session)
    await _open(db_session, [a, b])
    ra = await reservations.reserve(
        db_session, merchant_id=a, amount=Decimal("100"), idempotency_key=None
    )
    rb = await reservations.reserve(
        db_session, merchant_id=b, amount=Decimal("100"), idempotency_key=None
    )
    assert ra.amount_usdt == Decimal("100.00")
    assert rb.amount_usdt == Decimal("100.01")
    assert ra.address == OURS


@pytest.mark.asyncio
async def test_one_pending_per_merchant_and_idempotent_replay(db_session: AsyncSession) -> None:
    m = await _merchant(db_session)
    await _open(db_session, [m])
    first = await reservations.reserve(
        db_session, merchant_id=m, amount=Decimal("50"), idempotency_key="k1"
    )
    again = await reservations.reserve(
        db_session, merchant_id=m, amount=Decimal("50"), idempotency_key="k1"
    )
    assert again.id == first.id
    with pytest.raises(AppError) as exc:
        await reservations.reserve(
            db_session, merchant_id=m, amount=Decimal("60"), idempotency_key="k2"
        )
    assert _code(exc.value) == "usdt_reservation_open"
    with pytest.raises(AppError) as mismatch:
        await reservations.reserve(
            db_session, merchant_id=m, amount=Decimal("70"), idempotency_key="k1"
        )
    assert _code(mismatch.value) == "usdt_idempotency_mismatch"


@pytest.mark.asyncio
async def test_off_without_address_and_out_of_bounds(db_session: AsyncSession) -> None:
    m = await _merchant(db_session)
    with pytest.raises(AppError) as off:
        await reservations.reserve(
            db_session, merchant_id=m, amount=Decimal("50"), idempotency_key=None
        )
    assert _code(off.value) == "usdt_disabled"
    await _open(db_session, [m])
    for amount, code in (
        ("5", "usdt_amount_out_of_bounds"),
        ("50001", "usdt_amount_out_of_bounds"),
        ("10.001", "usdt_amount_precision"),
    ):
        with pytest.raises(AppError) as bad:
            await reservations.reserve(
                db_session, merchant_id=m, amount=Decimal(amount), idempotency_key=None
            )
        assert _code(bad.value) == code


# --- intake ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exact_transfer_credits_the_deposit_once(db_session: AsyncSession) -> None:
    m = await _merchant(db_session)
    await _open(db_session, [m])
    r = await reservations.reserve(
        db_session, merchant_id=m, amount=Decimal("250"), idempotency_key=None
    )
    before = await deposit_balance(db_session, merchant_id=m)
    t = _transfer("250")
    res = await intake.ingest(db_session, t, received_at=now())
    assert res.status == "matched"
    assert res.reservation_number == r.number
    assert await deposit_balance(db_session, merchant_id=m) == before + Decimal("250")
    await db_session.refresh(r)
    assert (r.status, r.holds_amount) == ("paid", True)
    assert r.quarantine_until is not None

    dup = await intake.ingest(db_session, t, received_at=now())
    assert dup.status == "duplicate"
    assert await deposit_balance(db_session, merchant_id=m) == before + Decimal("250")


@pytest.mark.asyncio
async def test_repeat_of_a_paid_amount_is_unmatched_and_alerts(db_session: AsyncSession) -> None:
    m = await _merchant(db_session)
    await _open(db_session, [m])
    await reservations.reserve(
        db_session, merchant_id=m, amount=Decimal("40"), idempotency_key=None
    )
    assert (await intake.ingest(db_session, _transfer("40"), received_at=now())).status == "matched"
    second = await intake.ingest(db_session, _transfer("40"), received_at=now())
    assert second.status == "unmatched"
    assert [k for k, _ in second.alerts] == ["usdt_unmatched"]


@pytest.mark.asyncio
async def test_wrong_amount_and_dust(db_session: AsyncSession) -> None:
    m = await _merchant(db_session)
    await _open(db_session, [m])
    await reservations.reserve(
        db_session, merchant_id=m, amount=Decimal("100"), idempotency_key=None
    )
    short = await intake.ingest(db_session, _transfer("99.00"), received_at=now())
    assert short.status == "unmatched"
    odd = await intake.ingest(db_session, _transfer("100.000001"), received_at=now())
    assert odd.status == "unmatched"
    dust = await intake.ingest(db_session, _transfer("0.000001"), received_at=now())
    assert (dust.status, dust.alerts) == ("ignored", [])


@pytest.mark.asyncio
async def test_on_time_transfer_read_after_expiry_still_pays(db_session: AsyncSession) -> None:
    """The block time is the chain's: a poller outage must not cost the reseller."""
    m = await _merchant(db_session)
    await _open(db_session, [m])
    r = await reservations.reserve(
        db_session, merchant_id=m, amount=Decimal("30"), idempotency_key=None
    )
    sent = _transfer("30")
    later = now() + timedelta(hours=3)
    await db_session.execute(
        update(UsdtReservation)
        .where(UsdtReservation.id == r.id)
        .values(expires_at=now() + timedelta(seconds=30))
    )
    await reservations.sweep(db_session, now_=later)
    res = await intake.ingest(db_session, sent, received_at=later)
    assert res.status == "matched"


@pytest.mark.asyncio
async def test_transfer_after_expiry_is_unmatched(db_session: AsyncSession) -> None:
    m = await _merchant(db_session)
    await _open(db_session, [m])
    r = await reservations.reserve(
        db_session, merchant_id=m, amount=Decimal("31"), idempotency_key=None
    )
    res = await intake.ingest(
        db_session,
        _transfer("31", at_offset=reservations.RESERVATION_TTL + timedelta(minutes=1)),
        received_at=now(),
    )
    assert res.status == "unmatched"
    await db_session.refresh(r)
    assert r.status != "paid"


@pytest.mark.asyncio
async def test_sent_then_cancelled_still_pays_but_sent_after_cancel_does_not(
    db_session: AsyncSession,
) -> None:
    m = await _merchant(db_session)
    await _open(db_session, [m])
    r = await reservations.reserve(
        db_session, merchant_id=m, amount=Decimal("32"), idempotency_key=None
    )
    sent_before = _transfer("32", at_offset=timedelta(seconds=-5))
    await reservations.cancel(db_session, merchant_id=m, number=r.number)
    assert (await intake.ingest(db_session, sent_before, received_at=now())).status == "matched"

    r2 = await reservations.reserve(
        db_session, merchant_id=m, amount=Decimal("33"), idempotency_key=None
    )
    await reservations.cancel(db_session, merchant_id=m, number=r2.number)
    after = await intake.ingest(
        db_session, _transfer("33", at_offset=timedelta(minutes=2)), received_at=now()
    )
    assert after.status == "unmatched"


# --- polling ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_reads_journals_credits_and_advances_the_cursor(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    m = await _merchant(db_session)
    await _open(db_session, [m])
    await reservations.reserve(
        db_session, merchant_id=m, amount=Decimal("120"), idempotency_key=None
    )
    await db_session.commit()
    block = int(now().timestamp() * 1000)
    rows = [
        _row("120000000", block_timestamp=block, transaction_id="c1" * 32),
        _row("5000000", block_timestamp=block, transaction_id="c2" * 32),
        _row(
            "120000000",
            transaction_id="c3" * 32,
            token_info={"address": _tron(7), "decimals": 6, "symbol": "USDT"},
        ),
    ]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"success": True, "data": rows, "meta": {}})

    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await poll.poll_once(sessions, now_=now(), http=http)
        again = await poll.poll_once(sessions, now_=now(), http=http)

    assert (result.seen, result.matched, result.unmatched) == (2, 1, 1)
    assert again.seen == 0
    assert seen[0].url.params["contract_address"] == USDT_CONTRACT
    assert seen[0].url.params["only_confirmed"] == "true"
    async with sessions() as db:
        s = await load_settings(db)
        assert s.cursor_block_ms == block
        assert await deposit_balance(db, merchant_id=m) >= Decimal("120")
        txs = set((await db.execute(select(UsdtIncoming.tx_id))).scalars())
        assert txs == {"c1" * 32, "c2" * 32}


@pytest.mark.asyncio
async def test_poll_does_nothing_when_off(db_engine: AsyncEngine) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("polled while off")

    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await poll.poll_once(sessions, now_=now(), http=http)
    assert result.seen == 0


# --- admin -----------------------------------------------------------------------

A = "/api/v1/admin/usdt"


def _k() -> dict[str, str]:
    return {"Idempotency-Key": f"usdt-admin-{new_id()}"}


@pytest.mark.asyncio
async def test_admin_settings_refuse_a_typo_and_reset_the_cursor(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    bad = await integration_client.patch(
        f"{A}/settings", headers={**admin_headers, **_k()}, json={"address": OURS[:-1] + "x"}
    )
    assert bad.status_code == 422, bad.text
    ok = await integration_client.patch(
        f"{A}/settings",
        headers={**admin_headers, **_k()},
        json={"address": OURS, "mode": "all", "min_amount_usd": "20"},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["address"] == OURS
    assert body["cursor_block_ms"] is not None
    assert Decimal(body["min_amount_usd"]) == Decimal("20")
    inverted = await integration_client.patch(
        f"{A}/settings", headers={**admin_headers, **_k()}, json={"max_amount_usd": "5"}
    )
    assert inverted.status_code == 422, inverted.text


@pytest.mark.asyncio
async def test_admin_credits_an_unmatched_transfer_once(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    m = await _merchant(db_session)
    await _open(db_session, [m])
    res = await intake.ingest(db_session, _transfer("77.123456"), received_at=now())
    assert res.status == "unmatched"
    await db_session.commit()
    row = await db_session.scalar(select(UsdtIncoming))
    assert row is not None
    row_id = row.id
    before = await deposit_balance(db_session, merchant_id=m)

    listed = await integration_client.get(
        f"{A}/incoming", params={"result": "unmatched"}, headers=admin_headers
    )
    assert [i["id"] for i in listed.json()["items"]] == [row.id]

    url = f"{A}/incoming/{row.id}/credit"
    first = await integration_client.post(
        url, headers={**admin_headers, **_k()}, json={"merchant_id": m, "note": "sent short"}
    )
    assert first.status_code == 200, first.text
    assert first.json()["result"] == "manual"
    assert first.json()["merchant_id"] == m
    again = await integration_client.post(
        url, headers={**admin_headers, **_k()}, json={"merchant_id": m}
    )
    assert again.status_code == 200, again.text
    db_session.expire_all()
    assert await deposit_balance(db_session, merchant_id=m) == before + Decimal("77.12")

    dismiss = await integration_client.post(
        f"{A}/incoming/{row_id}/dismiss", headers={**admin_headers, **_k()}, json={"note": "x"}
    )
    assert dismiss.status_code == 409, dismiss.text


@pytest.mark.asyncio
async def test_admin_dismisses(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    await _open(db_session, [])
    await intake.ingest(db_session, _transfer("12"), received_at=now())
    await db_session.commit()
    row = await db_session.scalar(select(UsdtIncoming))
    assert row is not None
    r = await integration_client.post(
        f"{A}/incoming/{row.id}/dismiss",
        headers={**admin_headers, **_k()},
        json={"note": "refunded to sender"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "dismissed"


# --- cabinet ---------------------------------------------------------------------

U = f"{BASE}/usdt"


@pytest.mark.asyncio
async def test_cabinet_flow(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    cabinet_mails: list[dict[str, str]],
) -> None:
    access, merchant_id = await _signed_up(integration_client, cabinet_mails, "u@acme.example.com")
    h = _auth(access)
    off = await integration_client.get(f"{U}/status", headers=h)
    assert off.json()["enabled"] is False

    await _open(db_session, [merchant_id])
    await db_session.commit()
    on = await integration_client.get(f"{U}/status", headers=h)
    assert on.json()["enabled"] is True
    assert on.json()["network"] == "TRC20"

    created = await integration_client.post(
        f"{U}/deposits", headers={**h, "Idempotency-Key": new_id()}, json={"amount": "150.50"}
    )
    assert created.status_code == 201, created.text
    dep = created.json()
    assert (dep["address"], Decimal(dep["amount"]), dep["status"]) == (
        OURS,
        Decimal("150.50"),
        "pending",
    )
    listed = await integration_client.get(f"{U}/deposits", headers=h)
    assert listed.json()["items"][0]["address"] is None

    await intake.ingest(db_session, _transfer("150.50"), received_at=now())
    await db_session.commit()
    paid = await integration_client.get(f"{U}/deposits/{dep['number']}", headers=h)
    assert paid.json()["status"] == "paid"
    assert paid.json()["address"] is None
    assert paid.json()["tx_id"]

    cancel = await integration_client.post(
        f"{U}/deposits/{dep['number']}/cancel", headers={**h, "Idempotency-Key": new_id()}
    )
    assert cancel.status_code == 409, cancel.text
