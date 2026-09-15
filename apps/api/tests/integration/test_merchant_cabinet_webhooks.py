"""The webhook screen: configure the endpoint, rotate its key, read the log.

These four writes were admin-only through M3a, and the reason was SSRF — a
stranger aiming our outbound worker at an address of their choosing. M4 hands
them to the merchant, so the tests that matter are the ones proving the
refusals did not move with the caller: `http://` and a private host are still
refused, now from a cabinet session.

The other half is scope. A webhook secret signs every delivery we send, and a
delivery log names a reseller's own order ids, so "one operator never touches
another merchant's hook" is tested on every route rather than spot-checked.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.config import Settings, get_settings
from yupay.core.ids import new_id
from yupay.modules.merchants import cabinet_routes
from yupay.modules.merchants.models import MerchantWebhook, MerchantWebhookDelivery

pytestmark = pytest.mark.asyncio

BASE = "/merchant/cabinet"
CABINET_URL = "https://reseller.yupay.test"
PASSWORD = "correct-horse-battery"


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Capture confirmation mail and point the cabinet at a base URL.

    Registration refuses outright when ``merchant_cabinet_url`` is empty, so
    this fixture is what makes sign-up reachable at all here.
    """
    mails: list[dict[str, str]] = []

    async def _send(*, to: str, subject: str, html: str, text: str) -> str:
        mails.append({"to": to, "html": html, "subject": subject, "text": text})
        return "msg-test"

    base = get_settings().model_dump()
    base["merchant_cabinet_url"] = CABINET_URL
    monkeypatch.setattr(cabinet_routes, "send_email", _send)
    monkeypatch.setattr(cabinet_routes, "get_settings", lambda: Settings(**base))
    return mails


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _key() -> dict[str, str]:
    """A fresh ``Idempotency-Key``. The API refuses anything under 16 chars."""
    return {"Idempotency-Key": f"cab-{uuid.uuid4()}"}


async def _signed_up(
    client: AsyncClient, mails: list[dict[str, str]], email: str
) -> tuple[str, str]:
    """Register and confirm. Returns ``(access_token, merchant_id)``."""
    r = await client.post(
        f"{BASE}/register",
        json={"email": email, "password": PASSWORD, "title": "ACME", "accept_offer": True},
    )
    assert r.status_code == 201, r.text
    link = re.search(r'href="([^"]+/confirm\?token=[^"]+)"', mails[-1]["html"])
    assert link is not None
    token = parse_qs(urlparse(link.group(1)).query)["token"][0]
    tokens = await client.post(f"{BASE}/confirm", json={"token": token})
    assert tokens.status_code == 200, tokens.text
    access = str(tokens.json()["access_token"])
    me = await client.get(f"{BASE}/me", headers=_auth(access))
    return access, str(me.json()["merchant_id"])


async def test_the_secret_exists_in_exactly_one_response(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """Set mints it, the read never carries it, and a replay does not re-mint.

    The replay half is the one worth the setup: ``idempotent_responses`` has no
    reaper, so a usable signing key persisted there would outlive every
    rotation. The stored snapshot must have ``secret: null``.
    """
    access, _ = await _signed_up(integration_client, sent, "hooks@acme.example.com")
    key = _key()

    first = await integration_client.put(
        f"{BASE}/webhook",
        headers={**_auth(access), **key},
        json={"url": "https://acme.example.com/yupay"},
    )
    replay = await integration_client.put(
        f"{BASE}/webhook",
        headers={**_auth(access), **key},
        json={"url": "https://acme.example.com/yupay"},
    )
    read = await integration_client.get(f"{BASE}/webhook", headers=_auth(access))

    assert first.status_code == 200, first.text
    assert isinstance(first.json()["secret"], str)
    assert first.json()["secret"].startswith("ypmw_")
    assert replay.status_code == 200
    assert replay.json()["secret"] is None, "a replay must not hand out key material"
    assert read.status_code == 200
    assert "secret" not in read.json(), "the read model has no such field"
    assert read.json()["url"] == "https://acme.example.com/yupay"


@pytest.mark.parametrize(
    "url",
    [
        "http://acme.example.com/yupay",  # not https
        "https://127.0.0.1/yupay",  # loopback
        "https://10.0.0.5/yupay",  # private range
        "https://localhost/yupay",
    ],
)
async def test_the_ssrf_refusals_did_not_move_with_the_caller(
    integration_client: AsyncClient, sent: list[dict[str, str]], url: str
) -> None:
    """The whole reason this was admin-only, now exercised from a cabinet session.

    The rules live in ``admin.validate_webhook_url``, which ``set_webhook``
    applies for every caller of the facade — so they hold here without this
    router restating them, which is the property that made handing the control
    over safe rather than merely convenient.
    """
    access, _ = await _signed_up(integration_client, sent, f"ssrf-{new_id()[:8]}@acme.example.com")

    refused = await integration_client.put(
        f"{BASE}/webhook", headers={**_auth(access), **_key()}, json={"url": url}
    )

    assert refused.status_code == 422, refused.text
    # And nothing was written: a refusal that left a row would deliver.
    assert (
        await integration_client.get(f"{BASE}/webhook", headers=_auth(access))
    ).status_code == 404


async def test_rotating_replaces_the_key_and_disabling_keeps_the_row(
    integration_client: AsyncClient, sent: list[dict[str, str]], db_session: AsyncSession
) -> None:
    """One live key at a time, and a disable that is a timestamp rather than a DELETE."""
    access, merchant_id = await _signed_up(integration_client, sent, "rot@acme.example.com")
    first = await integration_client.put(
        f"{BASE}/webhook",
        headers={**_auth(access), **_key()},
        json={"url": "https://acme.example.com/yupay"},
    )

    rotated = await integration_client.post(
        f"{BASE}/webhook/rotate-secret", headers={**_auth(access), **_key()}
    )
    disabled = await integration_client.delete(
        f"{BASE}/webhook", headers={**_auth(access), **_key()}
    )
    reenabled = await integration_client.put(
        f"{BASE}/webhook",
        headers={**_auth(access), **_key()},
        json={"url": "https://acme.example.com/hooks"},
    )

    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["secret"] != first.json()["secret"]
    assert disabled.status_code == 200
    assert disabled.json()["disabled_at"] is not None
    # A disable keeps the row — there is still exactly one, and the re-enable
    # edits it rather than re-onboarding with a fresh secret.
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
    assert reenabled.status_code == 200
    assert reenabled.json()["disabled_at"] is None
    assert reenabled.json()["secret"] is None, "changing the URL must not break a live verifier"


async def test_one_operator_never_touches_another_merchants_hook(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """Every route on this surface takes the merchant from the session.

    There is no id in any of these paths to get wrong, which is the point —
    the test is here so that a future route which *does* take one fails.
    """
    owner, _ = await _signed_up(integration_client, sent, "owner-h@acme.example.com")
    stranger, _ = await _signed_up(integration_client, sent, "stranger-h@other.example.com")
    await integration_client.put(
        f"{BASE}/webhook",
        headers={**_auth(owner), **_key()},
        json={"url": "https://acme.example.com/yupay"},
    )

    assert (
        await integration_client.get(f"{BASE}/webhook", headers=_auth(stranger))
    ).status_code == 404
    rotated = await integration_client.post(
        f"{BASE}/webhook/rotate-secret", headers={**_auth(stranger), **_key()}
    )
    assert rotated.status_code == 404

    # The owner's hook is untouched: same URL, and still deliverable.
    mine = await integration_client.get(f"{BASE}/webhook", headers=_auth(owner))
    assert mine.json()["url"] == "https://acme.example.com/yupay"
    assert mine.json()["disabled_at"] is None


async def test_the_delivery_log_is_this_merchants_only_and_pages(
    integration_client: AsyncClient, sent: list[dict[str, str]], db_session: AsyncSession
) -> None:
    """Newest first, keyset-paged, and scoped — a log names a reseller's own order ids."""
    mine, my_merchant = await _signed_up(integration_client, sent, "log@acme.example.com")
    theirs, their_merchant = await _signed_up(integration_client, sent, "log@other.example.com")

    for merchant_id, count in ((my_merchant, 3), (their_merchant, 1)):
        for index in range(count):
            db_session.add(
                MerchantWebhookDelivery(
                    id=new_id(),
                    merchant_id=merchant_id,
                    url="https://acme.example.com/yupay",
                    event_type="order.status_changed",
                    payload={"n": index, "owner": merchant_id},
                    status="delivered",
                    attempts_count=1,
                    next_attempt_at=datetime.now(UTC),
                    response_code=200,
                )
            )
    await db_session.commit()

    page = await integration_client.get(
        f"{BASE}/webhook/deliveries", headers=_auth(mine), params={"limit": 2}
    )
    assert page.status_code == 200, page.text
    assert len(page.json()["items"]) == 2
    assert page.json()["next_cursor"] is not None
    assert all(row["payload"]["owner"] == my_merchant for row in page.json()["items"])

    rest = await integration_client.get(
        f"{BASE}/webhook/deliveries",
        headers=_auth(mine),
        params={"limit": 2, "cursor": page.json()["next_cursor"]},
    )
    # The keyset property itself: the second page repeats nothing from the
    # first. An offset page under a log the worker is still writing would.
    assert {row["id"] for row in page.json()["items"]}.isdisjoint(
        {row["id"] for row in rest.json()["items"]}
    )
    assert len(rest.json()["items"]) == 1
    assert rest.json()["next_cursor"] is None, "the last page must say so"

    # The other merchant sees only their own row, whatever ours contains.
    theirs_page = await integration_client.get(f"{BASE}/webhook/deliveries", headers=_auth(theirs))
    assert [row["payload"]["owner"] for row in theirs_page.json()["items"]] == [their_merchant]


async def test_every_webhook_route_refuses_a_signed_out_browser(
    integration_client: AsyncClient,
) -> None:
    """Enumerated, not spot-checked: a route added without the dependency is
    silent otherwise."""
    assert (await integration_client.get(f"{BASE}/webhook")).status_code == 401
    assert (await integration_client.get(f"{BASE}/webhook/deliveries")).status_code == 401
    assert (
        await integration_client.put(f"{BASE}/webhook", json={"url": "https://x.example.com/h"})
    ).status_code == 401
    assert (await integration_client.post(f"{BASE}/webhook/rotate-secret")).status_code == 401
    assert (await integration_client.delete(f"{BASE}/webhook")).status_code == 401
