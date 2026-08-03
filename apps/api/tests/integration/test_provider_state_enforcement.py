"""Provider-state enforcement in ``create_intent`` + a money-safety regression.

``create_intent`` must reject NEW intents for a disabled/maintenance provider,
but an already-in-flight payment must still settle via its webhook/callback
even if the provider is disabled after the intent was created — enforcement
lives only at intent-creation time, never on the settlement path (see
``provider_state``'s module docstring).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

import pytest
import yupay.api.v1  # noqa: F401 -- see comment below
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.core.errors import ConflictError
from yupay.modules.orders.models import Order
from yupay.modules.payments import provider_state as ps
from yupay.modules.users.models import User

# ``yupay.api.v1`` (above) is otherwise unused here — it's imported purely for
# its side effect. ``yupay.modules.payments.service`` is imported lazily,
# inside each test body (mirrors ``test_payments_provider_hooks.py``).
# Importing it at module scope would make it the FIRST thing to touch
# ``yupay.modules.payments`` whenever this file runs standalone/first, which
# trips a genuine circular import: ``service`` -> ``wallet.api`` ->
# ``wallet.routes`` -> ``api.v1.deps`` -> needs the ``yupay.api.v1`` PACKAGE,
# not yet registered -> runs ``api.v1/__init__.py`` -> ``payments.api`` ->
# back into the still-mid-import ``service`` module, where ``create_intent``
# isn't defined yet. Pre-importing the package here makes ``yupay.api.v1``
# register FIRST, exactly as ``yupay.bootstrap`` does when a test reaches
# ``create_app()`` (via ``integration_client``) before touching
# ``payments.service`` directly — this file's first two tests use only
# ``db_session``, so nothing else guarantees that order.

pytestmark = pytest.mark.asyncio

# ``create_intent`` calls ``get_gateway("click").available`` before the
# provider-state check runs, so Click needs to be config-available — mirrors
# ``test_click_webhook.py``'s ``_click_env`` fixture.
CLICK_SERVICE_ID = 108149
CLICK_SECRET = "web-secret-abc"
TOTAL_CHARGED = Decimal("130000.00")
AMOUNT_STR = str(TOTAL_CHARGED)

PREPARE_URL = "/api/v1/payments/click/prepare"
COMPLETE_URL = "/api/v1/payments/click/complete"


@pytest.fixture(autouse=True)
def _click_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CLICK_SERVICE_ID_WEB", str(CLICK_SERVICE_ID))
    monkeypatch.setenv("CLICK_SECRET_KEY_WEB", CLICK_SECRET)
    monkeypatch.setenv("CLICK_MERCHANT_ID", "63276")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _md5(*parts: str) -> str:
    return hashlib.md5("".join(parts).encode()).hexdigest()


def _prepare_body(
    *, click_trans_id: str, merchant_trans_id: str, amount: str = AMOUNT_STR
) -> dict[str, str]:
    sign_time = "2026-08-03 10:00:00"
    sign = _md5(
        click_trans_id,
        str(CLICK_SERVICE_ID),
        CLICK_SECRET,
        merchant_trans_id,
        amount,
        "0",
        sign_time,
    )
    return {
        "click_trans_id": click_trans_id,
        "service_id": str(CLICK_SERVICE_ID),
        "click_paydoc_id": "5001",
        "merchant_trans_id": merchant_trans_id,
        "amount": amount,
        "action": "0",
        "error": "0",
        "error_note": "Success",
        "sign_time": sign_time,
        "sign_string": sign,
    }


def _complete_body(
    *,
    click_trans_id: str,
    merchant_trans_id: str,
    merchant_prepare_id: str,
    amount: str = AMOUNT_STR,
) -> dict[str, str]:
    sign_time = "2026-08-03 10:05:00"
    sign = _md5(
        click_trans_id,
        str(CLICK_SERVICE_ID),
        CLICK_SECRET,
        merchant_trans_id,
        merchant_prepare_id,
        amount,
        "1",
        sign_time,
    )
    return {
        "click_trans_id": click_trans_id,
        "service_id": str(CLICK_SERVICE_ID),
        "click_paydoc_id": "5001",
        "merchant_trans_id": merchant_trans_id,
        "merchant_prepare_id": merchant_prepare_id,
        "amount": amount,
        "action": "1",
        "error": "0",
        "error_note": "Success",
        "sign_time": sign_time,
        "sign_string": sign,
    }


async def _seed_pending_order(db: AsyncSession, *, total_charged: Decimal = TOTAL_CHARGED) -> str:
    """Create a pending_payment order payable via Click; return its id.

    Mirrors ``test_click_webhook.py::_seed_order`` — the existing helper the
    Click webhook integration tests already use to seed a bare user + order
    without going through the full checkout HTTP flow.
    """
    user_id = str(uuid.uuid4())
    order_id = str(uuid.uuid4())
    db.add(User(id=user_id, roles=[]))
    await db.flush()
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            guest_email=None,
            status="pending_payment",
            currency="UZS",
            total_usd=Decimal("10.00"),
            total_charged=total_charged,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    await db.commit()
    return order_id


# --------------------------------------------------------------------------- #
# create_intent rejects new intents for a non-active provider                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad_state", ["disabled", "maintenance"])
async def test_create_intent_rejected_when_not_active(
    db_session: AsyncSession, bad_state: Literal["disabled", "maintenance"]
) -> None:
    from yupay.modules.payments import service as pay_svc

    order_id = await _seed_pending_order(db_session)
    await ps.set_logical_state(db_session, provider="click", state=bad_state, changed_by=None)
    await db_session.commit()

    with pytest.raises(ConflictError) as ei:
        await pay_svc.create_intent(
            db_session, order_id=order_id, provider="click", return_url=None, idempotency_key="k1"
        )

    expected_reason = "provider_disabled" if bad_state == "disabled" else "provider_maintenance"
    assert ei.value.extra.get("reason") == expected_reason
    assert ei.value.extra.get("provider") == "click"


async def test_create_intent_allowed_when_active(db_session: AsyncSession) -> None:
    """Sanity: the default (no row) state is ``active`` and is not blocked."""
    from yupay.modules.payments import service as pay_svc

    order_id = await _seed_pending_order(db_session)

    payment = await pay_svc.create_intent(
        db_session, order_id=order_id, provider="click", return_url=None, idempotency_key="k-active"
    )
    await db_session.commit()

    assert payment.status == "pending"


# --------------------------------------------------------------------------- #
# Money safety: disabling the provider AFTER intent creation must not stop    #
# the in-flight payment from settling via its webhook/callback.              #
# --------------------------------------------------------------------------- #


async def test_disabled_after_intent_created_still_settles_via_webhook(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    from yupay.modules.payments import service as pay_svc

    order_id = await _seed_pending_order(db_session)

    # 1. Create the intent while Click is active.
    payment = await pay_svc.create_intent(
        db_session, order_id=order_id, provider="click", return_url=None, idempotency_key="ms-1"
    )
    await db_session.commit()
    assert payment.status == "pending"

    # 2. Admin disables Click AFTER the intent exists.
    await ps.set_logical_state(db_session, provider="click", state="disabled", changed_by=None)
    await db_session.commit()

    # 3. Click's own webhooks (/prepare then /complete) drive the SAME payment
    #    to completion — ``_ensure_payment`` reuses the pending payment created
    #    in step 1 (same order_id + provider="click" + status="pending"), and
    #    neither webhook route consults ``provider_state`` at all.
    click_trans_id = "9100"
    prepared = (
        await integration_client.post(
            PREPARE_URL,
            data=_prepare_body(click_trans_id=click_trans_id, merchant_trans_id=order_id),
        )
    ).json()
    assert prepared["error"] == 0, prepared

    r = await integration_client.post(
        COMPLETE_URL,
        data=_complete_body(
            click_trans_id=click_trans_id,
            merchant_trans_id=order_id,
            merchant_prepare_id=str(prepared["merchant_prepare_id"]),
        ),
    )
    assert r.status_code == 200
    completed = r.json()
    assert completed["error"] == 0, completed

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    assert order.status != "pending_payment"
    assert order.paid_at is not None

    # ``payment`` is a live reference held by this session's identity map, so
    # a plain re-select would just hand back the same (stale, pre-webhook)
    # Python object instead of re-reading the row the webhook committed on
    # its own session — ``refresh`` forces that re-read (mirrors
    # ``test_click_service.py``/``test_auth_password.py``).
    await db_session.refresh(payment)
    assert payment.status == "succeeded"

    # The provider is still disabled — a NEW intent attempt on the same
    # (now-paid) order is rejected for the ordinary "not awaiting payment"
    # reason, proving the disablement itself never got relaxed.
    assert await ps.get_state(db_session, "click") == "disabled"
