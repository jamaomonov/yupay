"""Signed-request authentication for the machine API (M2, Task 2; spec §9.2).

Exercises ``merchants.auth.merchant_auth`` end to end against a real mounted
app. ``/merchant/v1`` itself lands in Task 3, so this module mounts probe
routes under the real prefix and puts the dependency behind them — the shape a
Task 3/4/5 endpoint will have, without pre-empting their contracts.

The HMAC is recomputed here by hand rather than imported from
``merchants.signing``: a signature test that calls the implementation it is
testing proves only that the function is deterministic. The canonical string
below is transcribed from the module README, which is what a third party
implements against.

A signature is deliberately **not** single-use: a replaying attacker and a
retrying client send byte-identical requests, so no marker can separate them,
and single-use would break at-least-once retries on the money path.
``test_an_identical_retry_still_authenticates`` pins that, and would fail if
anyone re-introduced a burn marker.
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
from fastapi import APIRouter, Body, Depends
from httpx import ASGITransport, AsyncClient, Response
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
    """A full app (so the admin surface is reachable) plus probe routes.

    The probes are the only thing this fixture adds: a GET, a POST that echoes
    its JSON body, and a path-parameter GET, all under the real
    ``/merchant/v1`` prefix and guarded by ``merchant_auth`` and nothing else,
    so a failure here is the dependency's and not an endpoint's.

    The POST takes a real body parameter on purpose: without one FastAPI never
    reads the body, and the signed-body tests would prove nothing about the
    dependency co-existing with an endpoint that parses the same bytes.
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
    async def _probe_get(merchant: Annotated[Merchant, Depends(merchant_auth)]) -> dict[str, Any]:
        """Echo the authenticated merchant."""
        return {"merchant_id": merchant.id, "title": merchant.title}

    @probe.post("/_probe")
    async def _probe_post(
        merchant: Annotated[Merchant, Depends(merchant_auth)],
        payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        """Echo the authenticated merchant AND the parsed body."""
        return {"merchant_id": merchant.id, "echo": payload}

    @probe.get("/_probe/{tail:path}")
    async def _probe_tail(
        tail: str, merchant: Annotated[Merchant, Depends(merchant_auth)]
    ) -> dict[str, Any]:
        """Echo the routed path parameter — what ``scope["path"]`` decoded to."""
        return {"merchant_id": merchant.id, "tail": tail}

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
    query: str = "",
    body: bytes = b"",
    timestamp: int | None = None,
    sign_method: str | None = None,
    sign_path: str | None = None,
    sign_query: str | None = None,
) -> dict[str, str]:
    """Build the three auth headers, transcribing the README's scheme by hand.

    The ``sign_*`` overrides sign something other than what will be sent —
    that is the only way to test that a field is actually covered.
    """
    ts = str(int(time.time()) if timestamp is None else timestamp)
    message = "\n".join(
        (
            ts,
            (method if sign_method is None else sign_method).upper(),
            path if sign_path is None else sign_path,
            query if sign_query is None else sign_query,
            hashlib.sha256(body).hexdigest(),
        )
    ).encode()
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {
        "X-Merchant-Key": key_id,
        "X-Merchant-Timestamp": ts,
        "X-Merchant-Signature": signature,
    }


async def _call(
    client: AsyncClient,
    key_id: str,
    secret: str,
    *,
    method: str = "GET",
    path: str = PROBE_PATH,
    query: str = "",
    body: bytes = b"",
    extra: dict[str, str] | None = None,
    **sign: Any,
) -> Response:
    """Sign and send one request."""
    q = query
    headers = _signed(key_id, secret, method=method, path=path, query=q, body=body, **sign)
    if extra:
        headers.update(extra)
    if body:
        headers.setdefault("Content-Type", "application/json")
    url = f"{path}?{q}" if q else path
    return await client.request(method, url, headers=headers, content=body or None)


# ---------- the happy paths ----------


async def test_a_correct_signature_authenticates(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    r = await _call(machine_client, key_id, secret, query="")

    assert r.status_code == 200, r.text
    assert r.json()["merchant_id"] == merchant_id
    # Carry-over from Task 1's review: whatever Actor this eventually feeds
    # must carry a REAL uuid. `Actor.__post_init__` accepts `merchant_id=""`
    # and an empty string reaches Postgres as `uuid = ''` -> DataError -> 500.
    assert uuid.UUID(r.json()["merchant_id"])


async def test_a_correct_signature_over_a_body_authenticates_and_the_endpoint_still_parses_it(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """The dependency reads the body; FastAPI must still see it (I3).

    Without the echo assertion the signed-body tests prove only that the
    dependency ran, not that it left the stream usable for the endpoint.
    """
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)
    body = json.dumps({"merchant_order_id": "abc-1"}, separators=(",", ":")).encode()

    r = await _call(machine_client, key_id, secret, method="POST", body=body, query="")

    assert r.status_code == 200, r.text
    assert r.json()["merchant_id"] == merchant_id
    assert r.json()["echo"] == {"merchant_order_id": "abc-1"}


async def test_a_signed_query_string_authenticates(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    r = await _call(machine_client, key_id, secret, query="limit=10&status=paid")

    assert r.status_code == 200, r.text


@pytest.mark.parametrize("skew", [-299, 299])
async def test_both_edges_of_the_timestamp_window_are_accepted(
    machine_client: AsyncClient, admin_headers: dict[str, str], skew: int
) -> None:
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    r = await _call(machine_client, key_id, secret, timestamp=int(time.time()) + skew)

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
    headers = _signed(
        key_id, secret, method="POST", path=PROBE_PATH, query="", body=b'{"amount":"1.00"}'
    )

    r = await machine_client.post(
        PROBE_PATH,
        headers={**headers, "Content-Type": "application/json"},
        content=b'{"amount":"9999.00"}',
    )

    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


async def test_a_signature_over_a_different_path_is_401(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    r = await _call(
        machine_client, key_id, secret, sign_path="/merchant/v1/something-else", query=""
    )

    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


async def test_a_signature_over_a_different_method_is_401(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Sign GET, send POST. Only the path mismatch was covered before."""
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    r = await _call(
        machine_client,
        key_id,
        secret,
        method="POST",
        body=b"{}",
        query="",
        sign_method="GET",
    )

    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


async def test_a_signature_is_bound_to_the_query_string(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """The whole reason the query joined the canonical string.

    The edge access log records query strings verbatim, and the ±300 s window
    would otherwise make a lifted ``?limit=10`` replayable as
    ``?limit=100000``.
    """
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    lifted = await _call(
        machine_client, key_id, secret, query="limit=100000", sign_query="limit=10"
    )

    assert lifted.status_code == 401
    assert lifted.json()["code"] == "invalid_credentials"


async def test_two_raw_paths_that_route_the_same_have_different_signatures(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Signing the RAW request line, not the decoded path (the I5 fix).

    ``/_probe/a%2Fb`` and ``/_probe/a/b`` percent-decode to the same routing
    path and reach the same endpoint with the same parameters — so under the
    old scheme, which signed ``scope["path"]``, one signature covered both.
    Signing the bytes as they arrived makes the two distinct.
    """
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)
    encoded = f"{PROBE_PATH}/a%2Fb"

    crossed = await machine_client.get(
        encoded, headers=_signed(key_id, secret, path=f"{PROBE_PATH}/a/b", query="")
    )
    assert crossed.status_code == 401
    assert crossed.json()["code"] == "invalid_credentials"

    honest = await machine_client.get(
        encoded, headers=_signed(key_id, secret, path=encoded, query="")
    )
    assert honest.status_code == 200, honest.text
    # Signed raw, routed decoded — both endpoints see the same parameter.
    assert honest.json()["tail"] == "a/b"


async def test_a_percent_encoded_newline_in_the_path_never_authenticates(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """The delimiter hole, closed twice over.

    A signature computed as though ``%0A`` were a real field separator — for
    path ``/_probe/a`` plus query ``limit=100000`` — must never authenticate a
    request whose path literally contains ``%0A``. It cannot: the raw path is
    percent-encoded, so the signed field is the three characters ``%0A`` and
    the two readings differ (pinned exactly in the unit tests). Independently,
    Starlette's path-parameter regex refuses the decoded control character, so
    the request does not even reach the dependency — hence "not 200" rather
    than a specific status.
    """
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    forged = await machine_client.get(
        f"{PROBE_PATH}/a%0Alimit=100000",
        headers=_signed(key_id, secret, path=f"{PROBE_PATH}/a", query="limit=100000"),
    )

    assert forged.status_code != 200
    assert forged.status_code in {401, 404}


@pytest.mark.parametrize("skew", [-400, 400])
async def test_a_timestamp_outside_the_window_is_401(
    machine_client: AsyncClient, admin_headers: dict[str, str], skew: int
) -> None:
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    r = await _call(machine_client, key_id, secret, timestamp=int(time.time()) + skew)

    assert r.status_code == 401
    assert r.json()["code"] == "stale_timestamp"


@pytest.mark.parametrize(
    "value", ["not-a-number", "1_725_000_000", " 1725000000 ", "+1725000000", ""]
)
async def test_a_non_strict_timestamp_is_401(
    machine_client: AsyncClient, admin_headers: dict[str, str], value: str
) -> None:
    """``int()`` accepts all of these; "unix seconds" does not (M5).

    Not exploitable — the raw header is what gets signed, so the two sides
    cannot disagree — but clients would quietly diverge on what is legal.
    """
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)
    headers = {**_signed(key_id, secret), "X-Merchant-Timestamp": value}

    r = await machine_client.get(PROBE_PATH, headers=headers)

    assert r.status_code == 401
    assert r.json()["code"] in {"stale_timestamp", "missing_credentials"}


# An EMPTY signature header reads as a missing one, and is covered by
# ``test_missing_credential_headers_are_401`` — not here.
@pytest.mark.parametrize("bad", ["z" * 64, "ab" * 20, "0x" + "a" * 62])
async def test_a_malformed_signature_is_a_401_not_a_500(
    machine_client: AsyncClient, admin_headers: dict[str, str], bad: str
) -> None:
    """C1: ``compare_digest`` raises ``TypeError`` on a non-ASCII ``str``.

    With no catch-all handler in ``bootstrap`` that is a 500 and a Sentry
    traceback from an unauthenticated path — and it tells the caller that
    their input was malformed rather than that their credentials were wrong,
    which is the one thing this surface promises never to reveal.
    """
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)
    headers = {**_signed(key_id, secret), "X-Merchant-Signature": bad}

    r = await machine_client.get(PROBE_PATH, headers=headers)

    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


async def test_a_non_ascii_signature_header_is_a_401_not_a_500(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """C1, in its faithful form: raw high bytes on the wire.

    Starlette decodes header bytes as latin-1, so a raw ``0xC3`` arrives as a
    non-ASCII ``str`` — and ``hmac.compare_digest`` raises ``TypeError`` on
    one of those. With no catch-all handler in ``bootstrap`` that is a 500
    plus a Sentry traceback from an unauthenticated path. httpx refuses to
    encode a non-ASCII ``str`` header, which is why the values here are bytes
    — and why the string-valued tests above could never have caught it.
    """
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)
    signed = _signed(key_id, secret)

    raw: dict[str, Any] = {**signed, "X-Merchant-Signature": b"\xc3\xa9" * 32}
    r = await machine_client.get(PROBE_PATH, headers=raw)
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"

    # Same shape on the timestamp: Arabic-Indic digits, which ``int()``
    # happily accepts and ``[0-9]`` does not (M5).
    stamped: dict[str, Any] = {**signed, "X-Merchant-Timestamp": "١٧٢٥٠٠٠٠٠٠".encode()}
    r = await machine_client.get(PROBE_PATH, headers=stamped)
    assert r.status_code == 401
    assert r.json()["code"] == "stale_timestamp"


async def test_unknown_revoked_and_bad_signature_are_indistinguishable(
    machine_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """The three credential failures must return one body — spec §9.2.

    An early ``return`` on "no such key" would also skip the HMAC entirely;
    the implementation signs against a dummy secret instead, and this test
    pins the visible half of that.
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

    unknown = await _call(machine_client, "ypm_nosuchkeyatall", "irrelevant-secret")
    revoked = await _call(machine_client, doomed_key, doomed_secret)
    bad_sig = await _call(
        machine_client, good_key, good_secret, extra={"X-Merchant-Signature": "de" * 32}
    )

    assert unknown.status_code == revoked.status_code == bad_sig.status_code == 401
    assert unknown.json() == revoked.json() == bad_sig.json()
    assert unknown.json()["code"] == "invalid_credentials"
    # And the revoked row really is revoked, not merely mis-signed.
    row = (
        await db_session.execute(select(MerchantApiKey).where(MerchantApiKey.key_id == doomed_key))
    ).scalar_one()
    assert row.revoked_at is not None


async def test_an_identical_retry_still_authenticates(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """A signature is NOT single-use, and that is the deliberate choice.

    Round 1 burned each verified signature in Redis. It was reverted because a
    replaying attacker and a retrying client send byte-identical requests, so
    no marker separates them — single-use only breaks at-least-once retries,
    and it breaks them on the money path: a client resending after a reset
    connection would get an auth error for a network fault, and if the first
    attempt already created an order the caller would never learn it exists.
    Neither AWS SigV4 nor Stripe single-uses a signature for the same reason.

    Replay is bounded by the ±300 s window, by keeping credentials out of the
    edge access log (``infra/caddy/Caddyfile.prod``), and — for mutations — by
    ``merchant_order_id`` idempotency, which Task 4 owns. This test is what
    fails if anyone re-introduces the burn.
    """
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)
    headers = _signed(key_id, secret, query="")

    first = await machine_client.get(PROBE_PATH, headers=headers)
    retry = await machine_client.get(PROBE_PATH, headers=headers)

    assert first.status_code == 200, first.text
    assert retry.status_code == 200, retry.text
    assert retry.json()["merchant_id"] == first.json()["merchant_id"]


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

    r = await _call(machine_client, key_id, secret)

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

    inside_cidr = await _call(
        machine_client, key_id, secret, extra={"X-Forwarded-For": "203.0.113.42"}
    )
    exact_host = await _call(
        machine_client, key_id, secret, extra={"X-Forwarded-For": "198.51.100.7"}
    )
    outside = await _call(machine_client, key_id, secret, extra={"X-Forwarded-For": "198.51.100.8"})

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

    r = await _call(machine_client, key_id, secret, extra={"X-Forwarded-For": "192.0.2.55"})
    assert r.status_code == 200, r.text


async def test_the_allowlist_falls_back_to_the_transport_peer_without_a_forwarded_header(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Pins the inherited ``core.client_ip`` contract (I6).

    Every other IP test sets ``X-Forwarded-For`` explicitly, so the suite
    would pass unchanged if the edge stopped stripping the header — or if the
    helper stopped reading it. These two assertions pin both halves: with no
    header the transport peer decides, and the allowlist is enforced against
    it. The header itself is trusted only because the shared edge overwrites
    it; hardening ``client_ip`` with a trusted-proxy check is filed for M3,
    and the allowlist is defence-in-depth on top of the HMAC regardless.
    """
    merchant_id = await _new_merchant(machine_client, admin_headers)
    peer_key, peer_secret = await _new_key(
        machine_client, admin_headers, merchant_id, ip_allowlist=["127.0.0.1"]
    )
    elsewhere_key, elsewhere_secret = await _new_key(
        machine_client, admin_headers, merchant_id, ip_allowlist=["203.0.113.0/24"]
    )

    allowed = await _call(machine_client, peer_key, peer_secret)
    refused = await _call(machine_client, elsewhere_key, elsewhere_secret)

    assert allowed.status_code == 200, allowed.text
    assert refused.status_code == 403
    assert refused.json()["code"] == "ip_not_allowed"


async def test_only_the_first_forwarded_hop_decides(
    machine_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """A multi-hop ``a, b, c`` value resolves to ``a`` — the real client (I6)."""
    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(
        machine_client, admin_headers, merchant_id, ip_allowlist=["203.0.113.0/24"]
    )

    client_first = await _call(
        machine_client,
        key_id,
        secret,
        extra={"X-Forwarded-For": "203.0.113.9, 10.0.0.1, 10.0.0.2"},
    )
    client_last = await _call(
        machine_client, key_id, secret, extra={"X-Forwarded-For": "10.0.0.1, 203.0.113.9"}
    )

    assert client_first.status_code == 200, client_first.text
    assert client_last.status_code == 403


# ---------- last_used_at ----------


async def test_last_used_at_is_stamped_advances_and_is_throttled(
    machine_client: AsyncClient, admin_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Best-effort, and throttled: it advances, it just does not advance per request."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    merchant_id = await _new_merchant(machine_client, admin_headers)
    key_id, secret = await _new_key(machine_client, admin_headers, merchant_id)

    async def _stamp() -> datetime | None:
        db_session.expire_all()
        value: datetime | None = (
            await db_session.execute(
                select(MerchantApiKey.last_used_at).where(MerchantApiKey.key_id == key_id)
            )
        ).scalar_one()
        return value

    assert await _stamp() is None

    assert (await _call(machine_client, key_id, secret)).status_code == 200
    first = await _stamp()
    assert first is not None

    # A second call moments later must NOT rewrite the row — the throttle is
    # what keeps concurrent requests off one row's lock.
    assert (await _call(machine_client, key_id, secret)).status_code == 200
    assert await _stamp() == first

    stale = datetime.now(UTC) - timedelta(hours=2)
    await db_session.execute(
        update(MerchantApiKey).where(MerchantApiKey.key_id == key_id).values(last_used_at=stale)
    )
    await db_session.commit()

    assert (await _call(machine_client, key_id, secret)).status_code == 200
    second = await _stamp()
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
        responses = [await _call(machine_client, key_id, secret) for _ in range(4)]
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    statuses = [r.status_code for r in responses]
    assert statuses[:2] == [200, 200]
    assert 429 in statuses
    # A machine client with no ``Retry-After`` retries immediately, which is
    # the traffic that tripped the limit in the first place.
    throttled = next(r for r in responses if r.status_code == 429)
    assert int(throttled.headers["Retry-After"]) > 0
    assert throttled.json()["type"].endswith("/rate-limited")


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
            forged = await _call(
                machine_client, key_id, secret, extra={"X-Merchant-Signature": "ab" * 32}
            )
            assert forged.status_code == 401
        r = await _call(machine_client, key_id, secret)
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert r.status_code == 200, r.text
