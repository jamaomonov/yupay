"""Integration tests for the merchant webhook surface (M3a, Task 1).

Storage plus the only way to configure it in this milestone: an **admin**
write. The merchant gets this control from the cabinet in M4 — there is
deliberately no ``/merchant/v1`` write, because its only purpose would be to
point our own worker at an arbitrary address.

Four endpoints, exercised through the mounted app with real admin auth:

- ``PUT    /api/v1/admin/merchants/{id}/webhook`` — set the URL. Mints the
  secret on first use and returns it **once**; a later URL change keeps the
  secret and answers ``secret: null``.
- ``GET    /api/v1/admin/merchants/{id}/webhook`` — never returns the secret.
  Its response model has no such field at all.
- ``POST   /api/v1/admin/merchants/{id}/webhook/rotate-secret`` — replaces
  the secret, returning the new one once. The old one stops verifying.
- ``DELETE /api/v1/admin/merchants/{id}/webhook`` — disables (sets
  ``disabled_at``); naturally idempotent.

Two invariants get their own tests because they are the ones that would be
expensive to discover in production: the secret is **encrypted at rest, not
hashed** (an HMAC cannot be verified from a digest — ADR-0069), and the URL
is refused at save time if it names a private, loopback or link-local
address. That save-time check cannot catch DNS rebinding, and does not claim
to: the connect-time check is M3a Task 2's outbound client.
"""

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import crypto
from yupay.core.ids import new_id
from yupay.modules.merchants.models import (
    WEBHOOK_RESPONSE_BODY_MAX,
    MerchantWebhook,
    MerchantWebhookDelivery,
)
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"

HOOK_URL = "https://hooks.reseller.example/yupay"
OTHER_URL = "https://hooks.reseller.example/yupay/v2"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login(client: AsyncClient, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token: str = r.json()["access_token"]
    return token


async def _grant_admin(db_session: AsyncSession, tg_id: int) -> None:
    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()


@pytest.fixture
async def admin_headers(
    integration_client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    token = await _login(integration_client, tg_id=91)
    await _grant_admin(db_session, tg_id=91)
    return {"Authorization": f"Bearer {token}"}


async def _create_merchant(
    client: AsyncClient, headers: dict[str, str], title: str = "Pilot Reseller"
) -> str:
    r = await client.post("/api/v1/admin/merchants", headers=headers, json={"title": title})
    assert r.status_code == 201, r.text
    merchant_id: str = r.json()["id"]
    return merchant_id


async def _set_hook(
    client: AsyncClient,
    headers: dict[str, str],
    merchant_id: str,
    url: str = HOOK_URL,
) -> dict[str, object]:
    r = await client.put(
        f"/api/v1/admin/merchants/{merchant_id}/webhook", headers=headers, json={"url": url}
    )
    assert r.status_code == 200, r.text
    body: dict[str, object] = r.json()
    return body


# ---------- auth ----------


async def test_every_webhook_endpoint_requires_a_token(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    base = f"/api/v1/admin/merchants/{merchant_id}/webhook"

    assert (await integration_client.get(base)).status_code == 401
    assert (await integration_client.put(base, json={"url": HOOK_URL})).status_code == 401
    assert (await integration_client.post(f"{base}/rotate-secret")).status_code == 401
    assert (await integration_client.delete(base)).status_code == 401


async def test_non_admin_token_is_forbidden_everywhere(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    token = await _login(integration_client, tg_id=92)  # never granted admin
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/api/v1/admin/merchants/{merchant_id}/webhook"

    assert (await integration_client.get(base, headers=headers)).status_code == 403
    assert (
        await integration_client.put(base, headers=headers, json={"url": HOOK_URL})
    ).status_code == 403
    assert (
        await integration_client.post(f"{base}/rotate-secret", headers=headers)
    ).status_code == 403
    assert (await integration_client.delete(base, headers=headers)).status_code == 403


# ---------- setting the URL ----------


async def test_set_webhook_returns_the_secret_once_and_stores_it_encrypted(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The secret is a signing key, so it is encrypted at rest, not hashed.

    Same reasoning as ``merchant_api_keys`` (ADR-0069 §4): an HMAC cannot be
    verified without the key material, so a digest would either forbid the
    signature or become the signing key itself. Its own HKDF purpose label
    keeps it independent of the machine-API key's.
    """
    merchant_id = await _create_merchant(integration_client, admin_headers)

    body = await _set_hook(integration_client, admin_headers, merchant_id)

    secret = body["secret"]
    assert isinstance(secret, str)
    assert secret
    assert body["url"] == HOOK_URL
    assert body["merchant_id"] == merchant_id
    assert body["disabled_at"] is None
    assert body["failure_streak"] == 0
    assert body["last_success_at"] is None
    assert body["last_failure_at"] is None

    row = (
        await db_session.execute(
            select(MerchantWebhook).where(MerchantWebhook.merchant_id == merchant_id)
        )
    ).scalar_one()
    assert secret.encode() not in row.secret_enc
    assert len(row.secret_nonce) == crypto.NONCE_SIZE
    assert (
        crypto.decrypt(row.secret_enc, row.secret_nonce, purpose=crypto.PURPOSE_MERCHANT_WEBHOOK)
        == secret
    )


async def test_the_webhook_secret_has_its_own_purpose_key(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Decrypting with the machine-API purpose must fail — HKDF domain separation."""
    from nacl.exceptions import CryptoError

    merchant_id = await _create_merchant(integration_client, admin_headers)
    await _set_hook(integration_client, admin_headers, merchant_id)

    row = (
        await db_session.execute(
            select(MerchantWebhook).where(MerchantWebhook.merchant_id == merchant_id)
        )
    ).scalar_one()
    with pytest.raises(CryptoError):
        crypto.decrypt(row.secret_enc, row.secret_nonce, purpose=crypto.PURPOSE_MERCHANT_API_KEY)


async def test_get_webhook_never_returns_the_secret(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    created = await _set_hook(integration_client, admin_headers, merchant_id)

    r = await integration_client.get(
        f"/api/v1/admin/merchants/{merchant_id}/webhook", headers=admin_headers
    )

    assert r.status_code == 200, r.text
    assert "secret" not in r.text
    assert str(created["secret"]) not in r.text
    assert r.json()["url"] == HOOK_URL


async def test_setting_the_url_again_keeps_the_secret_and_does_not_return_it(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """One endpoint per merchant in v1, so a second PUT edits the same row.

    Changing where deliveries go must not silently invalidate the merchant's
    verifier — rotation is its own endpoint, deliberately.
    """
    merchant_id = await _create_merchant(integration_client, admin_headers)
    first = await _set_hook(integration_client, admin_headers, merchant_id)

    second = await _set_hook(integration_client, admin_headers, merchant_id, url=OTHER_URL)

    assert second["secret"] is None
    assert second["url"] == OTHER_URL
    db_session.expire_all()
    rows = (
        (
            await db_session.execute(
                select(MerchantWebhook).where(MerchantWebhook.merchant_id == merchant_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].url == OTHER_URL
    assert (
        crypto.decrypt(
            rows[0].secret_enc, rows[0].secret_nonce, purpose=crypto.PURPOSE_MERCHANT_WEBHOOK
        )
        == first["secret"]
    )


async def test_one_webhook_per_merchant_is_enforced_by_the_database(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """v1 is one endpoint per merchant — a unique constraint, not a convention."""
    merchant_id = await _create_merchant(integration_client, admin_headers)
    await _set_hook(integration_client, admin_headers, merchant_id)

    enc, nonce = crypto.encrypt("ypmw_second", purpose=crypto.PURPOSE_MERCHANT_WEBHOOK)
    db_session.add(
        MerchantWebhook(
            id=new_id(),
            merchant_id=merchant_id,
            url="https://hooks.reseller.example/second",
            secret_enc=enc,
            secret_nonce=nonce,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# ---------- URL validation at save time ----------


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.reseller.example/yupay",  # not https
        "ftp://hooks.reseller.example/yupay",
        "https://localhost/yupay",
        "https://anything.localhost/yupay",
        "https://box.internal/yupay",
        "https://127.0.0.1/yupay",
        "https://10.0.0.7/yupay",
        "https://192.168.1.10/yupay",
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata
        "https://2130706433/yupay",  # bare-integer 127.0.0.1
        "https://[::1]/yupay",
        "https://[fc00::1]/yupay",
        "https:///yupay",  # no host at all
    ],
)
async def test_set_webhook_refuses_a_non_public_destination(
    integration_client: AsyncClient, admin_headers: dict[str, str], url: str
) -> None:
    """The save-time check the catalog's image URLs already get, reused verbatim.

    It raises the bar; it is not hermetic — a hostname that resolves publicly
    now and privately at delivery time (DNS rebinding) passes here by design.
    Task 2's connect-time check is the control for that.
    """
    merchant_id = await _create_merchant(integration_client, admin_headers)

    r = await integration_client.put(
        f"/api/v1/admin/merchants/{merchant_id}/webhook",
        headers=admin_headers,
        json={"url": url},
    )

    assert r.status_code == 422, r.text


async def test_a_refused_url_leaves_no_webhook_row(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)

    r = await integration_client.put(
        f"/api/v1/admin/merchants/{merchant_id}/webhook",
        headers=admin_headers,
        json={"url": "https://169.254.169.254/"},
    )

    assert r.status_code == 422
    assert (
        await db_session.execute(
            select(MerchantWebhook).where(MerchantWebhook.merchant_id == merchant_id)
        )
    ).scalar_one_or_none() is None


async def test_set_webhook_unknown_merchant_404(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    r = await integration_client.put(
        f"/api/v1/admin/merchants/{new_id()}/webhook",
        headers=admin_headers,
        json={"url": HOOK_URL},
    )
    assert r.status_code == 404


# ---------- rotation ----------


async def test_rotate_replaces_the_secret_and_returns_the_new_one_once(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    original = await _set_hook(integration_client, admin_headers, merchant_id)

    r = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/webhook/rotate-secret", headers=admin_headers
    )

    assert r.status_code == 200, r.text
    rotated = r.json()["secret"]
    assert isinstance(rotated, str)
    assert rotated
    assert rotated != original["secret"]
    assert r.json()["url"] == HOOK_URL

    db_session.expire_all()
    row = (
        await db_session.execute(
            select(MerchantWebhook).where(MerchantWebhook.merchant_id == merchant_id)
        )
    ).scalar_one()
    # The old secret is gone, not archived: one live signing key at a time.
    assert (
        crypto.decrypt(row.secret_enc, row.secret_nonce, purpose=crypto.PURPOSE_MERCHANT_WEBHOOK)
        == rotated
    )

    later = await integration_client.get(
        f"/api/v1/admin/merchants/{merchant_id}/webhook", headers=admin_headers
    )
    assert rotated not in later.text


async def test_rotate_without_a_configured_webhook_is_404(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    r = await integration_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/webhook/rotate-secret", headers=admin_headers
    )
    assert r.status_code == 404


# ---------- disabling ----------


async def test_disable_sets_disabled_at_and_is_idempotent(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    await _set_hook(integration_client, admin_headers, merchant_id)

    first = await integration_client.delete(
        f"/api/v1/admin/merchants/{merchant_id}/webhook", headers=admin_headers
    )
    second = await integration_client.delete(
        f"/api/v1/admin/merchants/{merchant_id}/webhook", headers=admin_headers
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["disabled_at"] is not None
    # The first disable stands; a second call does not move the timestamp.
    assert second.json()["disabled_at"] == first.json()["disabled_at"]
    assert "secret" not in first.text

    db_session.expire_all()
    row = (
        await db_session.execute(
            select(MerchantWebhook).where(MerchantWebhook.merchant_id == merchant_id)
        )
    ).scalar_one()
    assert row.disabled_at is not None
    # Disabled, not deleted: the delivery log's merchant FK and the URL stay
    # readable, and re-enabling is a PUT rather than a re-onboarding.
    assert row.url == HOOK_URL


async def test_setting_a_url_re_enables_a_disabled_hook_and_clears_the_streak(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The recovery path after an auto-disable (M3a Task 4) is a fresh PUT."""
    merchant_id = await _create_merchant(integration_client, admin_headers)
    await _set_hook(integration_client, admin_headers, merchant_id)
    await integration_client.delete(
        f"/api/v1/admin/merchants/{merchant_id}/webhook", headers=admin_headers
    )
    await db_session.execute(
        update(MerchantWebhook)
        .where(MerchantWebhook.merchant_id == merchant_id)
        .values(failure_streak=9)
    )
    await db_session.commit()

    body = await _set_hook(integration_client, admin_headers, merchant_id, url=OTHER_URL)

    assert body["disabled_at"] is None
    assert body["failure_streak"] == 0
    assert body["secret"] is None  # re-enabling is not a rotation


async def test_disable_without_a_configured_webhook_is_404(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    r = await integration_client.delete(
        f"/api/v1/admin/merchants/{merchant_id}/webhook", headers=admin_headers
    )
    assert r.status_code == 404


async def test_get_without_a_configured_webhook_is_404(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    r = await integration_client.get(
        f"/api/v1/admin/merchants/{merchant_id}/webhook", headers=admin_headers
    )
    assert r.status_code == 404


async def test_reads_and_writes_are_isolated_per_merchant(
    integration_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    owner = await _create_merchant(integration_client, admin_headers, title="Owner")
    stranger = await _create_merchant(integration_client, admin_headers, title="Stranger")
    await _set_hook(integration_client, admin_headers, owner)

    r = await integration_client.get(
        f"/api/v1/admin/merchants/{stranger}/webhook", headers=admin_headers
    )

    assert r.status_code == 404


# ---------- idempotent replay, scoped per merchant ----------


async def test_set_webhook_replay_scope_is_per_merchant(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """One client key reused across two merchants must configure both."""
    first_merchant = await _create_merchant(integration_client, admin_headers, title="A")
    second_merchant = await _create_merchant(integration_client, admin_headers, title="B")
    headers = {**admin_headers, "Idempotency-Key": "merchants-webhook-set-0001"}

    first = await integration_client.put(
        f"/api/v1/admin/merchants/{first_merchant}/webhook",
        headers=headers,
        json={"url": HOOK_URL},
    )
    second = await integration_client.put(
        f"/api/v1/admin/merchants/{second_merchant}/webhook",
        headers=headers,
        json={"url": OTHER_URL},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["merchant_id"] == second_merchant
    assert second.json()["url"] == OTHER_URL
    db_session.expire_all()
    urls = {
        row.merchant_id: row.url
        for row in (await db_session.execute(select(MerchantWebhook))).scalars().all()
    }
    assert urls == {first_merchant: HOOK_URL, second_merchant: OTHER_URL}


async def test_set_webhook_replay_never_returns_the_secret_twice(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """``idempotent_responses`` has no reaper — a usable secret must not live there."""
    merchant_id = await _create_merchant(integration_client, admin_headers)
    headers = {**admin_headers, "Idempotency-Key": "merchants-webhook-set-0002"}

    first = await integration_client.put(
        f"/api/v1/admin/merchants/{merchant_id}/webhook", headers=headers, json={"url": HOOK_URL}
    )
    second = await integration_client.put(
        f"/api/v1/admin/merchants/{merchant_id}/webhook", headers=headers, json={"url": HOOK_URL}
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["secret"] is not None
    assert second.json()["secret"] is None
    assert first.json()["secret"] not in second.text
    db_session.expire_all()
    rows = (await db_session.execute(select(MerchantWebhook))).scalars().all()
    assert len(rows) == 1


async def test_rotate_replay_does_not_rotate_twice_and_hides_the_secret(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    await _set_hook(integration_client, admin_headers, merchant_id)
    headers = {**admin_headers, "Idempotency-Key": "merchants-webhook-rotate-0001"}
    path = f"/api/v1/admin/merchants/{merchant_id}/webhook/rotate-secret"

    first = await integration_client.post(path, headers=headers)
    second = await integration_client.post(path, headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["secret"] is None
    db_session.expire_all()
    row = (
        await db_session.execute(
            select(MerchantWebhook).where(MerchantWebhook.merchant_id == merchant_id)
        )
    ).scalar_one()
    # The replay did not mint a third secret over the second one.
    assert (
        crypto.decrypt(row.secret_enc, row.secret_nonce, purpose=crypto.PURPOSE_MERCHANT_WEBHOOK)
        == first.json()["secret"]
    )


async def test_disable_replay_scope_is_per_merchant(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    first_merchant = await _create_merchant(integration_client, admin_headers, title="A")
    second_merchant = await _create_merchant(integration_client, admin_headers, title="B")
    await _set_hook(integration_client, admin_headers, first_merchant)
    await _set_hook(integration_client, admin_headers, second_merchant)
    headers = {**admin_headers, "Idempotency-Key": "merchants-webhook-disable-0001"}

    first = await integration_client.delete(
        f"/api/v1/admin/merchants/{first_merchant}/webhook", headers=headers
    )
    second = await integration_client.delete(
        f"/api/v1/admin/merchants/{second_merchant}/webhook", headers=headers
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["merchant_id"] == second_merchant
    db_session.expire_all()
    rows = (await db_session.execute(select(MerchantWebhook))).scalars().all()
    assert all(row.disabled_at is not None for row in rows)


# ---------- the delivery outbox ----------


async def test_the_delivery_outbox_round_trips_a_jsonb_payload(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The outbox row Task 3 enqueues and Task 4 drains — and M4's delivery log.

    Money rides as a **string** in every payload (AGENTS.md §9): JSONB has no
    Decimal, and a float would round a merchant's balance.
    """
    merchant_id = await _create_merchant(integration_client, admin_headers)
    payload = {
        "event": "balance.credited",
        "merchant_id": merchant_id,
        "amount": str(Decimal("12.34")),
        "balance": str(Decimal("1012.34")),
        "nested": {"list": [1, 2, 3], "unicode": "код"},
    }

    delivery_id = new_id()
    db_session.add(
        MerchantWebhookDelivery(
            id=delivery_id,
            merchant_id=merchant_id,
            event_type="balance.credited",
            payload=payload,
        )
    )
    await db_session.commit()
    # Drop the in-session copy so the assertions below read what Postgres
    # stored — including the columns that are server defaults.
    db_session.expire_all()

    stored = (
        await db_session.execute(
            select(MerchantWebhookDelivery).where(MerchantWebhookDelivery.id == delivery_id)
        )
    ).scalar_one()
    assert stored.payload == payload
    assert stored.payload["amount"] == "12.34"
    # The claimable-status vocabulary Tasks 3 and 4 both spell.
    assert stored.status == "pending"
    assert stored.attempts_count == 0
    assert stored.next_attempt_at is None
    assert stored.response_code is None
    assert stored.response_body is None
    assert stored.last_error is None
    assert stored.created_at is not None
    assert stored.updated_at is not None


async def test_the_delivery_status_vocabulary_is_enforced_by_a_check_constraint(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _create_merchant(integration_client, admin_headers)
    db_session.add(
        MerchantWebhookDelivery(
            id=new_id(),
            merchant_id=merchant_id,
            event_type="order.status_changed",
            payload={},
            status="in_flight",  # not one of ours
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_the_response_body_column_is_bounded(
    integration_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """``response_body`` is attacker-influenced text rendered in M4's cabinet.

    The cap is a column bound, not a convention, so an unbounded body cannot
    reach the database even if a future writer forgets to truncate.
    """
    merchant_id = await _create_merchant(integration_client, admin_headers)
    db_session.add(
        MerchantWebhookDelivery(
            id=new_id(),
            merchant_id=merchant_id,
            event_type="order.status_changed",
            payload={},
            status="failed",
            response_code=500,
            response_body="x" * (WEBHOOK_RESPONSE_BODY_MAX + 1),
        )
    )
    with pytest.raises(Exception):  # noqa: B017,PT011 -- asyncpg raises DataError via SQLAlchemy
        await db_session.flush()
    await db_session.rollback()

    db_session.add(
        MerchantWebhookDelivery(
            id=new_id(),
            merchant_id=merchant_id,
            event_type="order.status_changed",
            payload={},
            status="failed",
            response_code=500,
            response_body="x" * WEBHOOK_RESPONSE_BODY_MAX,
        )
    )
    await db_session.flush()
    await db_session.rollback()
