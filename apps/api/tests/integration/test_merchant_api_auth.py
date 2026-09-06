"""Signed-request authentication for the machine API (M2, Task 2; spec §9.2).

Exercises ``merchants.auth.merchant_auth`` end to end against a real mounted
app. ``/merchant/v1`` itself lands in Task 3, so this module mounts a probe
route under the real prefix and puts the dependency behind it — the shape a
Task 3/4/5 endpoint will have, without pre-empting their contracts.

The HMAC is recomputed here by hand rather than imported from
``merchants.signing``: a signature test that calls the implementation it is
testing proves only that the function is deterministic. The canonical string
below is transcribed from the module README, which is what a third party
implements against.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from yupay.modules.merchants.auth import merchant_auth
from yupay.modules.merchants.models import Merchant, MerchantApiKey
from yupay.modules.users.models import TelegramLink, User

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "123456:TEST"
PROBE_PATH = "/merchant/v1/_probe"


# ---------- harness ----------


@pytest.fixture
async def machine_client(db_engine) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]  # conftest fixture is untyped
    """A full app (so the admin surface is reachable) plus a probe route.

    The probe is the only thing this fixture adds: one GET and one POST under
    the real ``/merchant/v1`` prefix, guarded by ``merchant_auth`` and nothing
    else, so a failure here is the dependency's and not an endpoint's.
    """
    from yupay.bootstrap import create_app
    from yupay.core import db as core_db
    from yupay.core import redis as core_redis

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    core_db._engine = db_engine  # type: ignore[attr-defined]
    core_db._session_factory = factory  # type: ignore[attr-defined]
    core_redis._client = None  # type: ignore[attr-defined]

    app = create_app()
    probe = APIRouter(prefix="/merchant/v1")

    @probe.get("/_probe")
    async def _probe_get(merchant: Annotated[Merchant, Depends(merchant_auth)]) -> dict[str, str]:
        """Echo the authenticated merchant."""
        return {"merchant_id": merchant.id, "title": merchant.title}

    @probe.post("/_probe")
    async def _probe_post(merchant: Annotated[Merchant, Depends(merchant_auth)]) -> dict[str, str]:
        """Echo the authenticated merchant (body-carrying variant)."""
        return {"merchant_id": merchant.id, "title": merchant.title}

    app.include_router(probe)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    core_db._engine = None  # type: ignore[attr-defined]
    core_db._session_factory = None  # type: ignore[attr-defined]
    await core_redis.close_redis()


def _sign_init_data(fields: dict[str, str]) -> str:
    from urllib.parse import urlencode

    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


@pytest.fixture
async def admin_headers(machine_client: AsyncClient, db_session: AsyncSession) -> dict[str, str]:
    """Log a Telegram user in and grant it the admin role."""
    user_json = json.dumps({"id": 77, "first_name": "Admin"}, separators=(",", ":"))
    init_data = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await machine_client.post("/api/v1/auth/telegram/webapp", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    from sqlalchemy import update

    user_id = (
        await db_session.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == 77)
        )
    ).scalar_one()
    await db_session.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


async def _new_merchant(
    client: AsyncClient, headers: dict[str, str], title: str = "Reseller"
) -> str:
    r = await client.post("/api/v1/admin/merchants", headers=headers, json={"title": title})
    assert r.status_code == 201, r.text
    merchant_id: str = r.json()["id"]
    return merchant_id


async def _new_key(
    client: AsyncClient,
    headers: dict[str, str],
    merchant_id: str,
    *,
    label: str = "server",
    ip_allowlist: list[str] | None = None,
) -> tuple[str, str]:
    """Issue a key through the admin write path; returns ``(key_id, secret)``."""
    body: dict[str, Any] = {"label": label}
    if ip_allowlist is not None:
        body["ip_allowlist"] = ip_allowlist
    r = await client.post(
        f"/api/v1/admin/merchants/{merchant_id}/api-keys", headers=headers, json=body
    )
    assert r.status_code == 201, r.text
    payload = r.json()
    return payload["key_id"], payload["secret"]


def _signed(
    key_id: str,
    secret: str,
    *,
    method: str = "GET",
    path: str = PROBE_PATH,
    body: bytes = b"",
    timestamp: int | None = None,
    sign_path: str | None = None,
    sign_body: bytes | None = None,
) -> dict[str, str]:
    """Build the three auth headers, transcribing the README's scheme by hand."""
    ts = str(int(time.time()) if timestamp is None else timestamp)
    signing_key = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    message = f"{ts}\n{method.upper()}\n{path if sign_path is None else sign_path}\n".encode() + (
        body if sign_body is None else sign_body
    )
    signature = hmac.new(signing_key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {
        "X-Merchant-Key": key_id,
        "X-Merchant-Timestamp": ts,
        "X-Merchant-Signature": signature,
    }


# ---------- the happy paths ----------


async def test_a_correct_signature_authenticates(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    r = await machine_client.get(PROBE_PATH, headers=_signed(key_id, secret))

    assert r.status_code == 200, r.text
    assert r.json()["merchant_id"] == merchant_id
    # Carry-over from Task 1's review: whatever Actor this eventually feeds
    # must carry a REAL uuid. `Actor.__post_init__` accepts `merchant_id=""`
    # and an empty string reaches Postgres as `uuid = ''` -> DataError -> 500.
    assert uuid.UUID(r.json()["merchant_id"])


async def test_a_correct_signature_over_a_body_authenticates(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)
    body = json.dumps({"merchant_order_id": "abc-1"}, separators=(",", ":")).encode()

    r = await machine_client.post(
        PROBE_PATH,
        headers={
            **_signed(key_id, secret, method="POST", body=body),
            "Content-Type": "application/json",
        },
        content=body,
    )

    assert r.status_code == 200, r.text
    assert r.json()["merchant_id"] == merchant_id


async def test_the_edge_of_the_timestamp_window_is_still_accepted(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    r = await machine_client.get(
        PROBE_PATH, headers=_signed(key_id, secret, timestamp=int(time.time()) - 299)
    )

    assert r.status_code == 200, r.text


# ---------- the 401s ----------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Merchant-Key": "ypm_whatever"},
        {"X-Merchant-Key": "ypm_whatever", "X-Merchant-Timestamp": "1757000000"},
        {"X-Merchant-Key": "ypm_whatever", "X-Merchant-Signature": "00"},
    ],
)
async def test_missing_credential_headers_are_401(
    machine_client: AsyncClient, headers: dict[str, str]
) -> None:
    r = await machine_client.get(PROBE_PATH, headers=headers)
    assert r.status_code == 401
    assert r.json()["code"] == "missing_credentials"


async def test_a_tampered_body_is_401(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)
    signed_body = b'{"amount":"1.00"}'

    r = await machine_client.post(
        PROBE_PATH,
        headers=_signed(key_id, secret, method="POST", body=signed_body),
        content=b'{"amount":"9999.00"}',
    )

    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


async def test_a_signature_over_a_different_path_is_401(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    r = await machine_client.get(
        PROBE_PATH, headers=_signed(key_id, secret, sign_path="/merchant/v1/something-else")
    )

    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


@pytest.mark.parametrize("skew", [-400, 400])
async def test_a_timestamp_outside_the_window_is_401(
    machine_client: AsyncClient, admin_headers: dict[str, str], skew: int
) -> None:
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    r = await machine_client.get(
        PROBE_PATH, headers=_signed(key_id, secret, timestamp=int(time.time()) + skew)
    )

    assert r.status_code == 401
    assert r.json()["code"] == "stale_timestamp"


async def test_a_non_numeric_timestamp_is_401(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)
    headers = {**_signed(key_id, secret), "X-Merchant-Timestamp": "not-a-number"}

    r = await machine_client.get(PROBE_PATH, headers=headers)

    assert r.status_code == 401
    assert r.json()["code"] == "stale_timestamp"


async def test_unknown_revoked_and_bad_signature_are_indistinguishable(
    machine_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The three credential failures must return one body — spec §9.2.

    An early ``return`` on "no such key" would also make the unknown-key case
    measurably faster than a real HMAC comparison; the implementation signs
    against a dummy key instead, and this test pins the visible half of that.
    """
    merchant_id = await _new_merchant(machine_client, admin_headers)
    good_key, good_secret = await _new_key(machine_client, admin_headers, merchant_id)
    doomed_key, doomed_secret = await _new_key(
        machine_client, admin_headers, merchant_id, label="rotated-out"
    )
    r = await machine_client.delete(
        f"/api/v1/admin/merchants/{merchant_id}/api-keys/{doomed_key}", headers=admin_headers
    )
    assert r.status_code == 200, r.text

    unknown = await machine_client.get(
        PROBE_PATH, headers=_signed("ypm_nosuchkeyatall", "irrelevant-secret")
    )
    revoked = await machine_client.get(PROBE_PATH, headers=_signed(doomed_key, doomed_secret))
    bad_sig = await machine_client.get(
        PROBE_PATH, headers={**_signed(good_key, good_secret), "X-Merchant-Signature": "de" * 32}
    )

    assert unknown.status_code == revoked.status_code == bad_sig.status_code == 401
    assert unknown.json() == revoked.json() == bad_sig.json()
    assert unknown.json()["code"] == "invalid_credentials"
    # And the revoked row really is revoked, not merely mis-signed.
    row = (
        await db_session.execute(select(MerchantApiKey).where(MerchantApiKey.key_id == doomed_key))
    ).scalar_one()
    assert row.revoked_at is not None


# ---------- the 403s ----------


async def test_a_frozen_merchant_is_403_merchant_frozen(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)
    r = await machine_client.post(
        f"/api/v1/admin/merchants/{merchant_id}/freeze", headers=admin_headers
    )
    assert r.status_code == 200, r.text

    r = await machine_client.get(PROBE_PATH, headers=_signed(key_id, secret))

    assert r.status_code == 403
    assert r.json()["code"] == "merchant_frozen"


async def test_ip_allowlist_round_trips_through_the_write_path_and_is_enforced(
    machine_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Store two CIDRs, read them back, then match and non-match (carry-over 2).

    ``merchant_api_keys.ip_allowlist`` is the codebase's first ``ARRAY(INET)``
    and until now only its read path had ever run, so the assertions below go
    through the admin write endpoint, the admin read endpoint AND a direct row
    read before testing the filter itself.
    """
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(
        machine_client,
        admin_headers,
        merchant_id,
        ip_allowlist=["203.0.113.0/24", "198.51.100.7"],
    )

    row = (
        await db_session.execute(select(MerchantApiKey).where(MerchantApiKey.key_id == key_id))
    ).scalar_one()
    assert row.ip_allowlist == ["203.0.113.0/24", "198.51.100.7"]

    listed = await machine_client.get(
        f"/api/v1/admin/merchants/{merchant_id}/api-keys", headers=admin_headers
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["ip_allowlist"] == ["203.0.113.0/24", "198.51.100.7"]

    inside_cidr = await machine_client.get(
        PROBE_PATH, headers={**_signed(key_id, secret), "X-Forwarded-For": "203.0.113.42"}
    )
    exact_host = await machine_client.get(
        PROBE_PATH, headers={**_signed(key_id, secret), "X-Forwarded-For": "198.51.100.7"}
    )
    outside = await machine_client.get(
        PROBE_PATH, headers={**_signed(key_id, secret), "X-Forwarded-For": "198.51.100.8"}
    )

    assert inside_cidr.status_code == 200, inside_cidr.text
    assert exact_host.status_code == 200, exact_host.text
    assert outside.status_code == 403
    assert outside.json()["code"] == "ip_not_allowed"


async def test_a_null_allowlist_accepts_any_address(
    machine_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    row = (
        await db_session.execute(select(MerchantApiKey).where(MerchantApiKey.key_id == key_id))
    ).scalar_one()
    assert row.ip_allowlist is None

    r = await machine_client.get(
        PROBE_PATH, headers={**_signed(key_id, secret), "X-Forwarded-For": "192.0.2.55"}
    )
    assert r.status_code == 200, r.text


# ---------- last_used_at ----------


async def test_last_used_at_is_stamped_and_advances(
    machine_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Best-effort, and throttled: it advances, it just does not advance per request."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    assert (
        await db_session.execute(
            select(MerchantApiKey.last_used_at).where(MerchantApiKey.key_id == key_id)
        )
    ).scalar_one() is None

    r = await machine_client.get(PROBE_PATH, headers=_signed(key_id, secret))
    assert r.status_code == 200, r.text
    first = (
        await db_session.execute(
            select(MerchantApiKey.last_used_at).where(MerchantApiKey.key_id == key_id)
        )
    ).scalar_one()
    assert first is not None

    stale = datetime.now(UTC) - timedelta(hours=2)
    await db_session.execute(
        update(MerchantApiKey).where(MerchantApiKey.key_id == key_id).values(last_used_at=stale)
    )
    await db_session.commit()

    r = await machine_client.get(PROBE_PATH, headers=_signed(key_id, secret))
    assert r.status_code == 200, r.text
    second = (
        await db_session.execute(
            select(MerchantApiKey.last_used_at).where(MerchantApiKey.key_id == key_id)
        )
    ).scalar_one()
    assert second is not None
    assert second > stale


# ---------- throttling ----------


async def test_the_per_key_counter_returns_429(
    machine_client: AsyncClient, admin_headers: dict[str, str], monkeypatch
) -> None:  # type: ignore[no-untyped-def]  # pytest's monkeypatch fixture is untyped
    """The merchant axis, keyed on ``key_id`` — charged only once authenticated."""
    from yupay.core.config import get_settings

    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    monkeypatch.setenv("MERCHANT_API_KEY_RATE_MAX", "2")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        statuses = [
            (await machine_client.get(PROBE_PATH, headers=_signed(key_id, secret))).status_code
            for _ in range(4)
        ]
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert statuses[:2] == [200, 200]
    assert 429 in statuses


async def test_a_forged_key_id_cannot_spend_a_merchants_quota(
    machine_client: AsyncClient, admin_headers: dict[str, str], monkeypatch
) -> None:  # type: ignore[no-untyped-def]  # pytest's monkeypatch fixture is untyped
    """Unauthenticated traffic is bounded by the IP axis, never the merchant's."""
    from yupay.core.config import get_settings

    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    monkeypatch.setenv("MERCHANT_API_KEY_RATE_MAX", "2")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        for _ in range(6):
            forged = await machine_client.get(
                PROBE_PATH,
                headers={**_signed(key_id, secret), "X-Merchant-Signature": "ab" * 32},
            )
            assert forged.status_code == 401
        r = await machine_client.get(PROBE_PATH, headers=_signed(key_id, secret))
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert r.status_code == 200, r.text
