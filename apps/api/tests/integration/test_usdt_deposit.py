"""USDT (TRC20) top-up: reservations, chain intake, admin and cabinet (ADR-0104).

Polling and the TronGrid client are in ``test_usdt_poll.py``. Several tests
here pin the 2026-11-11 security review: each names the attack it closes.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from yupay.core.clock import now
from yupay.core.errors import AppError
from yupay.core.ids import new_id
from yupay.modules.merchants.deposit import deposit_balance
from yupay.modules.usdt import intake, reservations, resolve
from yupay.modules.usdt.address import is_tron_address
from yupay.modules.usdt.models import UsdtIncoming, UsdtNetwork, UsdtReservation
from yupay.modules.usdt.tron import USDT_CONTRACT

from tests.integration.cabinet_signup import BASE
from tests.integration.cabinet_signup import auth as _auth
from tests.integration.cabinet_signup import signed_up as _signed_up
from tests.integration.p2p_fixtures import _code, _merchant
from tests.integration.usdt_fixtures import EVM_OURS, OURS, open_usdt, reserve, transfer, tron


def test_address_check_accepts_real_and_refuses_typos() -> None:
    assert is_tron_address(USDT_CONTRACT)
    assert is_tron_address(OURS)
    assert not is_tron_address(OURS[:-1] + ("A" if OURS[-1] != "A" else "B"))
    assert not is_tron_address("0x2C77989B3b7C6bA635BCB366D89480c4422756E4")
    assert not is_tron_address("")


# --- reservations ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_free_amount_is_held_exactly_and_a_taken_one_is_offered_with_cents(
    db_session: AsyncSession,
) -> None:
    """Owner's rule: 100 if free; if held, offer 100.xx and hold nothing until asked."""
    a, b = await _merchant(db_session), await _merchant(db_session)
    await open_usdt(db_session, [a, b])
    assert (await reserve(db_session, a, "100")).amount_usdt == Decimal("100.00")
    with pytest.raises(AppError) as taken:
        await reserve(db_session, b, "100")
    assert _code(taken.value) == "usdt_amount_taken"
    offered = Decimal(str(taken.value.extra["suggested"]))
    assert Decimal("100.01") <= offered <= Decimal("100.99")
    held_by_b = await db_session.scalar(
        select(UsdtReservation).where(UsdtReservation.merchant_id == b)
    )
    assert held_by_b is None
    assert (await reserve(db_session, b, str(offered))).amount_usdt == offered


@pytest.mark.asyncio
async def test_no_offer_beyond_the_maximum(db_session: AsyncSession) -> None:
    a, b = await _merchant(db_session), await _merchant(db_session)
    await open_usdt(db_session, [a, b])
    await reserve(db_session, a, "50000")
    with pytest.raises(AppError) as busy:
        await reserve(db_session, b, "50000")
    assert _code(busy.value) == "usdt_amount_busy"


@pytest.mark.asyncio
async def test_networks_hold_amounts_separately_and_pay_only_their_own(
    db_session: AsyncSession,
) -> None:
    a, b = await _merchant(db_session), await _merchant(db_session)
    await open_usdt(db_session, [a, b], networks=("trc20", "bep20"))
    on_tron = await reserve(db_session, a, "100")
    on_bsc = await reserve(db_session, b, "100", "bep20")
    assert on_tron.amount_usdt == on_bsc.amount_usdt == Decimal("100.00")
    res = await intake.ingest(
        db_session, transfer("100", network="bep20", event_key="0"), received_at=now()
    )
    assert res.reservation_number == on_bsc.number
    await db_session.refresh(on_tron)
    assert on_tron.status == "pending"


@pytest.mark.asyncio
async def test_bep20_and_erc20_on_one_address_never_share_an_amount(
    db_session: AsyncSession,
) -> None:
    """Review 9: a send on the wrong chain must not pay someone else's hold."""
    a, b = await _merchant(db_session), await _merchant(db_session)
    await open_usdt(db_session, [a, b], networks=("bep20", "erc20"))
    await reserve(db_session, a, "100", "erc20")
    with pytest.raises(AppError) as taken:
        await reserve(db_session, b, "100", "bep20")
    assert _code(taken.value) == "usdt_amount_taken"


@pytest.mark.asyncio
async def test_a_network_without_a_start_point_is_not_open(db_session: AsyncSession) -> None:
    """Review 2: reserving before the poller fixed its start could go unread."""
    m = await _merchant(db_session)
    await open_usdt(db_session, [m], networks=("bep20",))
    row = await db_session.get(UsdtNetwork, "bep20")
    assert row is not None
    row.cursor = None
    await db_session.flush()
    with pytest.raises(AppError) as closed:
        await reserve(db_session, m, "100", "bep20")
    assert _code(closed.value) == "usdt_network_disabled"


@pytest.mark.asyncio
async def test_turning_a_paused_network_back_on_restarts_it(db_session: AsyncSession) -> None:
    """Review 8: resuming an old cursor would replay months of the address's history."""
    await open_usdt(db_session, [], networks=())
    row = await db_session.get(UsdtNetwork, "erc20")
    assert row is not None
    await resolve.reenable(db_session, row, True)
    assert (row.enabled, row.cursor) == (True, None)


@pytest.mark.asyncio
async def test_an_address_change_reports_what_it_closed(db_session: AsyncSession) -> None:
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    await reserve(db_session, m, "100")
    row = await db_session.get(UsdtNetwork, "trc20")
    assert row is not None
    alert = await resolve.change_address(db_session, row, tron(9))
    assert alert is not None
    assert OURS in alert
    assert tron(9) in alert
    assert "1" in alert


@pytest.mark.asyncio
async def test_a_closed_network_refuses_reservations(db_session: AsyncSession) -> None:
    m = await _merchant(db_session)
    await open_usdt(db_session, [m], networks=("trc20",))
    with pytest.raises(AppError) as closed:
        await reserve(db_session, m, "100", "erc20")
    assert _code(closed.value) == "usdt_network_disabled"


@pytest.mark.asyncio
async def test_one_pending_per_merchant_and_idempotent_replay(db_session: AsyncSession) -> None:
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    first = await reservations.reserve(
        db_session, merchant_id=m, network="trc20", amount=Decimal("50"), idempotency_key="k1"
    )
    again = await reservations.reserve(
        db_session, merchant_id=m, network="trc20", amount=Decimal("50"), idempotency_key="k1"
    )
    assert again.id == first.id
    with pytest.raises(AppError) as exc:
        await reservations.reserve(
            db_session, merchant_id=m, network="trc20", amount=Decimal("60"), idempotency_key="k2"
        )
    assert _code(exc.value) == "usdt_reservation_open"
    with pytest.raises(AppError) as mismatch:
        await reservations.reserve(
            db_session, merchant_id=m, network="trc20", amount=Decimal("70"), idempotency_key="k1"
        )
    assert _code(mismatch.value) == "usdt_idempotency_mismatch"


@pytest.mark.asyncio
async def test_reserve_and_cancel_is_capped_per_hour(db_session: AsyncSession) -> None:
    """One reseller cannot hold every cent of a popular amount to lock others out."""
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    for i in range(reservations.HOURLY_LIMIT):
        r = await reserve(db_session, m, str(100 + i))
        await reservations.cancel(db_session, merchant_id=m, number=r.number)
    with pytest.raises(AppError) as capped:
        await reserve(db_session, m, "500")
    assert _code(capped.value) == "usdt_too_many"


@pytest.mark.asyncio
async def test_off_without_address_and_out_of_bounds(db_session: AsyncSession) -> None:
    m = await _merchant(db_session)
    with pytest.raises(AppError) as off:
        await reserve(db_session, m, "50")
    assert _code(off.value) == "usdt_disabled"
    await open_usdt(db_session, [m])
    for amount, code in (
        ("5", "usdt_amount_out_of_bounds"),
        ("50001", "usdt_amount_out_of_bounds"),
        ("10.001", "usdt_amount_precision"),
    ):
        with pytest.raises(AppError) as bad:
            await reserve(db_session, m, amount)
        assert _code(bad.value) == code


# --- intake ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exact_transfer_credits_the_deposit_once(db_session: AsyncSession) -> None:
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    r = await reserve(db_session, m, "250")
    before = await deposit_balance(db_session, merchant_id=m)
    t = transfer(r.amount_usdt)
    res = await intake.ingest(db_session, t, received_at=now())
    assert (res.status, res.reservation_number) == ("matched", r.number)
    assert await deposit_balance(db_session, merchant_id=m) == before + r.amount_usdt
    await db_session.refresh(r)
    assert (r.status, r.holds_amount) == ("paid", True)

    assert (await intake.ingest(db_session, t, received_at=now())).status == "duplicate"
    assert await deposit_balance(db_session, merchant_id=m) == before + r.amount_usdt


@pytest.mark.asyncio
async def test_a_transfer_already_on_chain_cannot_be_claimed_by_reserving_after_it(
    db_session: AsyncSession,
) -> None:
    """Security review #1: the address is public and blocks show before confirmation."""
    thief = await _merchant(db_session)
    await open_usdt(db_session, [thief])
    r = await reserve(db_session, thief, "100")
    # Someone else's transfer of that exact amount, in a block 30 s before the
    # hold (the fixture made the hold two minutes ago).
    stolen = transfer(r.amount_usdt, at_offset=-timedelta(minutes=2, seconds=30))
    res = await intake.ingest(db_session, stolen, received_at=now())
    assert res.status == "unmatched"
    await db_session.refresh(r)
    assert r.status == "pending"


@pytest.mark.asyncio
async def test_a_transfer_seconds_after_the_hold_is_credited(db_session: AsyncSession) -> None:
    """Owner, 2026-11-25: no "too soon" hold — a transfer mined after its
    reservation pays it, however soon (the front-running risk falls only on a
    sender without a matching reservation, and is accepted)."""
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    r = await reserve(db_session, m, "250")  # created two minutes ago
    sent = transfer(r.amount_usdt, at_offset=-timedelta(minutes=1, seconds=55))  # +5 s
    assert (await intake.ingest(db_session, sent, received_at=now())).status == "matched"


@pytest.mark.asyncio
async def test_a_fast_honest_bep20_transfer_is_credited(db_session: AsyncSession) -> None:
    """2026-11-25: an honest BEP20 transfer 40 s after the hold was held back by
    the old one-minute guard."""
    m = await _merchant(db_session)
    await open_usdt(db_session, [m], networks=("bep20",))
    r = await reserve(db_session, m, "20", network="bep20")
    sent = transfer(r.amount_usdt, at_offset=-timedelta(minutes=1, seconds=20), network="bep20")
    assert (await intake.ingest(db_session, sent, received_at=now())).status == "matched"


@pytest.mark.asyncio
async def test_repeat_of_a_paid_amount_is_unmatched_and_alerts(db_session: AsyncSession) -> None:
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    r = await reserve(db_session, m, "40")
    assert (await intake.ingest(db_session, transfer(r.amount_usdt), received_at=now())).status == (
        "matched"
    )
    second = await intake.ingest(db_session, transfer(r.amount_usdt), received_at=now())
    assert second.status == "unmatched"
    assert [k for k, _ in second.alerts] == ["usdt_unmatched"]


@pytest.mark.asyncio
async def test_short_other_odd_and_dust_never_match(db_session: AsyncSession) -> None:
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    r = await reserve(db_session, m, "100")
    for amount in ("99.00", "100.01", f"{r.amount_usdt}0001"):
        assert (await intake.ingest(db_session, transfer(amount), received_at=now())).status == (
            "unmatched"
        )
    dust = await intake.ingest(db_session, transfer("0.5"), received_at=now())
    assert (dust.status, dust.alerts) == ("ignored", [])


@pytest.mark.asyncio
async def test_two_transfers_in_one_transaction_are_both_journaled(
    db_session: AsyncSession,
) -> None:
    """Security review #4: a batch payout carries several events under one tx id."""
    a, b = await _merchant(db_session), await _merchant(db_session)
    await open_usdt(db_session, [a, b])
    ra, rb = await reserve(db_session, a, "100"), await reserve(db_session, b, "250")
    first = transfer(ra.amount_usdt)
    second = transfer(rb.amount_usdt, tx=first.tx_id)
    assert (await intake.ingest(db_session, first, received_at=now())).status == "matched"
    assert (await intake.ingest(db_session, second, received_at=now())).status == "matched"
    count = len((await db_session.execute(select(UsdtIncoming.id))).all())
    assert count == 2


@pytest.mark.asyncio
async def test_on_time_transfer_read_after_expiry_still_pays(db_session: AsyncSession) -> None:
    """The block time is the chain's: a poller outage must not cost the reseller."""
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    r = await reserve(db_session, m, "30")
    sent = transfer(r.amount_usdt, at_offset=timedelta(seconds=10))
    await db_session.execute(
        update(UsdtReservation)
        .where(UsdtReservation.id == r.id)
        .values(expires_at=now() + timedelta(seconds=30))
    )
    later = now() + timedelta(hours=3)
    await reservations.sweep(db_session, now_=later)
    assert (await intake.ingest(db_session, sent, received_at=later)).status == "matched"


@pytest.mark.asyncio
async def test_a_late_match_does_not_reclaim_an_amount_someone_else_now_holds(
    db_session: AsyncSession,
) -> None:
    """Security review #3: re-holding broke the open-amount index and stalled the poller."""
    a, b = await _merchant(db_session), await _merchant(db_session)
    await open_usdt(db_session, [a, b])
    ra = await reserve(db_session, a, "100")
    sent = transfer(ra.amount_usdt, at_offset=timedelta(seconds=10))
    await db_session.execute(
        update(UsdtReservation)
        .where(UsdtReservation.id == ra.id)
        .values(expires_at=now() + timedelta(seconds=30))
    )
    await reservations.sweep(db_session, now_=now() + timedelta(hours=2))
    rb = UsdtReservation(
        id=new_id(),
        number=reservations.new_number(),
        merchant_id=b,
        network="trc20",
        address=OURS,
        amount_usdt=ra.amount_usdt,
        status="pending",
        holds_amount=True,
        created_at=now() + timedelta(hours=2),
        expires_at=now() + timedelta(hours=3),
    )
    db_session.add(rb)
    await db_session.flush()
    res = await intake.ingest(db_session, sent, received_at=now() + timedelta(hours=2))
    assert res.status == "matched"
    await db_session.refresh(ra)
    assert (ra.status, ra.holds_amount) == ("paid", False)


@pytest.mark.asyncio
async def test_transfer_after_expiry_or_to_another_address_is_unmatched(
    db_session: AsyncSession,
) -> None:
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    r = await reserve(db_session, m, "31")
    late = transfer(r.amount_usdt, at_offset=reservations.RESERVATION_TTL + timedelta(minutes=1))
    assert (await intake.ingest(db_session, late, received_at=now())).status == "unmatched"
    elsewhere = replace(transfer(r.amount_usdt), to_address=tron(5))
    assert (await intake.ingest(db_session, elsewhere, received_at=now())).status == "unmatched"


@pytest.mark.asyncio
async def test_sent_then_cancelled_still_pays_but_sent_after_cancel_does_not(
    db_session: AsyncSession,
) -> None:
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    r = await reserve(db_session, m, "32")
    sent_before = transfer(r.amount_usdt)
    await reservations.cancel(db_session, merchant_id=m, number=r.number)
    assert (await intake.ingest(db_session, sent_before, received_at=now())).status == "matched"

    r2 = await reserve(db_session, m, "33")
    await reservations.cancel(db_session, merchant_id=m, number=r2.number)
    after = transfer(r2.amount_usdt, at_offset=timedelta(minutes=2))
    assert (await intake.ingest(db_session, after, received_at=now())).status == "unmatched"


# --- admin -----------------------------------------------------------------------

A = "/api/v1/admin/usdt"


def _k() -> dict[str, str]:
    return {"Idempotency-Key": f"usdt-admin-{new_id()}"}


@pytest.mark.asyncio
async def test_admin_settings_and_a_network_address(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    ok = await integration_client.patch(
        f"{A}/settings",
        headers={**admin_headers, **_k()},
        json={"mode": "all", "min_amount_usd": "20"},
    )
    assert ok.status_code == 200, ok.text
    assert Decimal(ok.json()["min_amount_usd"]) == Decimal("20")
    assert [n["network"] for n in ok.json()["networks"]] == ["trc20", "bep20", "erc20"]
    inverted = await integration_client.patch(
        f"{A}/settings", headers={**admin_headers, **_k()}, json={"max_amount_usd": "5"}
    )
    assert inverted.status_code == 422, inverted.text

    typo = await integration_client.patch(
        f"{A}/networks/trc20", headers={**admin_headers, **_k()}, json={"address": OURS[:-1] + "x"}
    )
    assert typo.status_code == 422, typo.text
    # A TRON address on an EVM chain, and an EVM address without its checksum.
    for net, bad in (("bep20", OURS), ("erc20", EVM_OURS.lower())):
        wrong = await integration_client.patch(
            f"{A}/networks/{net}", headers={**admin_headers, **_k()}, json={"address": bad}
        )
        assert wrong.status_code == 422, wrong.text
    on = await integration_client.patch(
        f"{A}/networks/bep20",
        headers={**admin_headers, **_k()},
        json={"address": EVM_OURS, "enabled": True},
    )
    assert on.status_code == 200, on.text
    bep = next(n for n in on.json()["networks"] if n["network"] == "bep20")
    assert (bep["address"], bep["enabled"], bep["cursor"]) == (EVM_OURS, True, None)


@pytest.mark.asyncio
async def test_changing_an_address_closes_only_that_networks_pending_reservations(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Security review #8: a pending row kept showing an address nobody reads."""
    a, b = await _merchant(db_session), await _merchant(db_session)
    await open_usdt(db_session, [a, b], networks=("trc20", "bep20"))
    on_tron = (await reserve(db_session, a, "100")).id
    on_bsc = (await reserve(db_session, b, "100", "bep20")).id
    await db_session.commit()
    moved = await integration_client.patch(
        f"{A}/networks/trc20", headers={**admin_headers, **_k()}, json={"address": tron(9)}
    )
    assert moved.status_code == 200, moved.text
    db_session.expire_all()
    tron_row = await db_session.get(UsdtReservation, on_tron)
    bsc_row = await db_session.get(UsdtReservation, on_bsc)
    assert tron_row is not None
    assert bsc_row is not None
    assert (tron_row.status, bsc_row.status) == ("expired", "pending")


@pytest.mark.asyncio
async def test_admin_credits_an_unmatched_transfer_once(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    assert (
        await intake.ingest(db_session, transfer("77.123456"), received_at=now())
    ).status == "unmatched"
    await db_session.commit()
    row = await db_session.scalar(select(UsdtIncoming))
    assert row is not None
    row_id = row.id
    before = await deposit_balance(db_session, merchant_id=m)

    listed = await integration_client.get(
        f"{A}/incoming", params={"result": "unmatched"}, headers=admin_headers
    )
    assert [i["id"] for i in listed.json()["items"]] == [row_id]

    url = f"{A}/incoming/{row_id}/credit"
    first = await integration_client.post(
        url, headers={**admin_headers, **_k()}, json={"merchant_id": m, "note": "sent short"}
    )
    assert first.status_code == 200, first.text
    assert (first.json()["result"], first.json()["merchant_id"]) == ("manual", m)
    # A retry spelling the same id in upper case is the same credit, not a 409.
    again = await integration_client.post(
        url, headers={**admin_headers, **_k()}, json={"merchant_id": m.upper()}
    )
    assert again.status_code == 200, again.text
    other = await _merchant(db_session)
    await db_session.commit()
    elsewhere = await integration_client.post(
        url, headers={**admin_headers, **_k()}, json={"merchant_id": other}
    )
    assert elsewhere.status_code == 409, elsewhere.text
    db_session.expire_all()
    assert await deposit_balance(db_session, merchant_id=m) == before + Decimal("77.12")

    dismiss = await integration_client.post(
        f"{A}/incoming/{row_id}/dismiss", headers={**admin_headers, **_k()}, json={"note": "x"}
    )
    assert dismiss.status_code == 409, dismiss.text


@pytest.mark.asyncio
async def test_admin_cannot_credit_a_matched_transfer(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    m = await _merchant(db_session)
    await open_usdt(db_session, [m])
    r = await reserve(db_session, m, "60")
    await intake.ingest(db_session, transfer(r.amount_usdt), received_at=now())
    await db_session.commit()
    row = await db_session.scalar(select(UsdtIncoming))
    assert row is not None
    paid_twice = await integration_client.post(
        f"{A}/incoming/{row.id}/credit", headers={**admin_headers, **_k()}, json={"merchant_id": m}
    )
    assert paid_twice.status_code == 409, paid_twice.text


@pytest.mark.asyncio
async def test_admin_dismisses(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    await open_usdt(db_session, [])
    await intake.ingest(db_session, transfer("12"), received_at=now())
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

    await open_usdt(db_session, [merchant_id])
    await db_session.commit()
    on = await integration_client.get(f"{U}/status", headers=h)
    assert (on.json()["enabled"], on.json()["networks"]) == (True, ["trc20"])

    created = await integration_client.post(
        f"{U}/deposits",
        headers={**h, "Idempotency-Key": new_id()},
        json={"amount": "150.50", "network": "trc20"},
    )
    assert created.status_code == 201, created.text
    dep = created.json()
    assert (dep["address"], dep["status"]) == (OURS, "pending")
    assert Decimal(dep["amount"]) == Decimal("150.50")
    listed = await integration_client.get(f"{U}/deposits", headers=h)
    assert listed.json()["items"][0]["address"] is None

    # Mined well after the hold, as an honest payer's would be.
    await intake.ingest(
        db_session, transfer(dep["amount"], at_offset=timedelta(seconds=90)), received_at=now()
    )
    await db_session.commit()
    paid = await integration_client.get(f"{U}/deposits/{dep['number']}", headers=h)
    assert (paid.json()["status"], paid.json()["address"]) == ("paid", None)
    assert paid.json()["tx_id"]

    cancel = await integration_client.post(
        f"{U}/deposits/{dep['number']}/cancel", headers={**h, "Idempotency-Key": new_id()}
    )
    assert cancel.status_code == 409, cancel.text


@pytest.mark.asyncio
async def test_cabinet_list_is_one_query_for_the_transactions(
    integration_client: AsyncClient,
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    cabinet_mails: list[dict[str, str]],
) -> None:
    """AGENTS.md §10: the list must not look up each paid row's transaction alone."""
    access, merchant_id = await _signed_up(integration_client, cabinet_mails, "n@acme.example.com")
    await open_usdt(db_session, [merchant_id])
    for amount in ("20", "30", "40"):
        r = await reserve(db_session, merchant_id, amount)
        await intake.ingest(db_session, transfer(r.amount_usdt), received_at=now())
    await db_session.commit()

    statements: list[str] = []

    def _count(*args: object) -> None:
        statements.append(str(args[2]))

    event.listen(db_engine.sync_engine, "before_cursor_execute", _count)
    try:
        listed = await integration_client.get(f"{U}/deposits", headers=_auth(access))
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _count)
    assert len(listed.json()["items"]) == 3
    assert sum("FROM usdt_incoming" in s for s in statements) == 1
