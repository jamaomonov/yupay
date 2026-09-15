"""Sign-up and sign-in for the merchant cabinet.

The rules being pinned here are the ones that are cheap to get wrong and
expensive to discover: an unconfirmed address cannot sign in, a confirmation
link works once, a rotated refresh token is dead, and — the one that matters
most — a signed-in operator sees their own merchant and nobody else's.

Registration is **open** (spec §11), which is what makes the confirmation link
load-bearing rather than a formality: without it, anybody could register
someone else's address and read wholesale prices under their name.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.config import Settings, get_settings
from yupay.modules.auth import jwt as authjwt
from yupay.modules.merchants import cabinet_auth_routes
from yupay.modules.merchants.models import Merchant, MerchantSession, MerchantUser

pytestmark = pytest.mark.asyncio

BASE = "/merchant/cabinet"
CABINET_URL = "https://reseller.yupay.test"
PASSWORD = "correct-horse-battery"


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Capture the confirmation mail instead of sending it, and configure a URL."""
    mails: list[dict[str, str]] = []

    async def _send(*, to: str, subject: str, html: str, text: str) -> str:
        mails.append({"to": to, "subject": subject, "html": html, "text": text})
        return "msg-test"

    base = get_settings().model_dump()
    base["merchant_cabinet_url"] = CABINET_URL
    monkeypatch.setattr(cabinet_auth_routes, "send_email", _send)
    monkeypatch.setattr(cabinet_auth_routes, "get_settings", lambda: Settings(**base))
    return mails


def _token_from(mail: dict[str, str]) -> str:
    """Pull the confirmation token out of the link we actually mailed.

    Parsed from the mail rather than minted in the test: the thing under test
    is the link a person receives, and a test that mints its own token would
    keep passing if the route mailed the wrong one.
    """
    match = re.search(r'href="([^"]+/confirm\?token=[^"]+)"', mail["html"])
    assert match is not None, "no confirmation link in the mail"
    token = parse_qs(urlparse(match.group(1)).query)["token"][0]
    assert match.group(1).startswith(CABINET_URL)
    return token


async def _register(client: AsyncClient, email: str, **over: Any) -> Any:
    body = {
        "email": email,
        "password": PASSWORD,
        "title": "ACME Digital",
        "accept_offer": True,
        **over,
    }
    return await client.post(f"{BASE}/register", json=body)


async def _confirmed(client: AsyncClient, mails: list[dict[str, str]], email: str) -> str:
    """Register, confirm, and return the access token."""
    assert (await _register(client, email)).status_code == 201
    r = await client.post(f"{BASE}/confirm", json={"token": _token_from(mails[-1])})
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_registration_creates_a_merchant_and_an_unconfirmed_operator(
    integration_client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, str]]
) -> None:
    r = await _register(integration_client, "ops@acme.example.com")

    assert r.status_code == 201
    assert r.content == b"", "the response must not echo anything about the address"
    user = (
        await db_session.execute(
            select(MerchantUser).where(MerchantUser.email == "ops@acme.example.com")
        )
    ).scalar_one()
    assert user.email_confirmed_at is None
    assert user.offer_version is not None
    assert user.offer_accepted_at is not None
    merchant = await db_session.get(Merchant, user.merchant_id)
    assert merchant is not None
    assert merchant.title == "ACME Digital"
    assert len(sent) == 1
    assert sent[0]["to"] == "ops@acme.example.com"


async def test_an_unconfirmed_operator_cannot_sign_in(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """The link is the only proof of the mailbox, so it gates the first sign-in."""
    assert (await _register(integration_client, "slow@acme.example.com")).status_code == 201

    r = await integration_client.post(
        f"{BASE}/login", json={"email": "slow@acme.example.com", "password": PASSWORD}
    )

    assert r.status_code == 401


async def test_an_unknown_address_and_a_wrong_password_answer_the_same(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """Open registration makes this a real leak, not a theoretical one.

    A distinguishable "no such account" tells a prober which addresses have
    registered with us — somebody else's business relationship, disclosed.
    """
    await _confirmed(integration_client, sent, "real@acme.example.com")

    unknown = await integration_client.post(
        f"{BASE}/login", json={"email": "nobody@acme.example.com", "password": PASSWORD}
    )
    wrong = await integration_client.post(
        f"{BASE}/login", json={"email": "real@acme.example.com", "password": "not-the-password"}
    )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


async def test_a_confirmation_link_works_once(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """A link that works twice works for whoever reads the mailbox second."""
    assert (await _register(integration_client, "once@acme.example.com")).status_code == 201
    token = _token_from(sent[-1])

    assert (
        await integration_client.post(f"{BASE}/confirm", json={"token": token})
    ).status_code == 200
    second = await integration_client.post(f"{BASE}/confirm", json={"token": token})

    assert second.status_code == 401


async def test_the_offer_must_be_accepted(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """A checkbox that can be omitted is a checkbox nobody ticked."""
    r = await _register(integration_client, "noofferr@acme.example.com", accept_offer=False)

    assert r.status_code == 422
    assert sent == []


async def test_a_duplicate_address_is_refused(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    assert (await _register(integration_client, "dupe@acme.example.com")).status_code == 201

    again = await _register(integration_client, "dupe@acme.example.com")

    assert again.status_code == 409
    assert again.json()["code"] == "email_taken"


async def test_a_rotated_refresh_token_is_dead(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """Rotation is what makes a stolen token usable once and then noisy."""
    assert (await _register(integration_client, "rot@acme.example.com")).status_code == 201
    first = await integration_client.post(f"{BASE}/confirm", json={"token": _token_from(sent[-1])})
    old_refresh = first.json()["refresh_token"]

    rotated = await integration_client.post(f"{BASE}/refresh", json={"refresh_token": old_refresh})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != old_refresh

    replayed = await integration_client.post(f"{BASE}/refresh", json={"refresh_token": old_refresh})
    assert replayed.status_code == 401


async def test_signing_out_kills_that_session_and_its_access_token(
    integration_client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, str]]
) -> None:
    """The reason ``sid`` is in the payload: a perfectly valid JWT must stop
    working the moment its session is revoked, not when it expires."""
    assert (await _register(integration_client, "out@acme.example.com")).status_code == 201
    tokens = (
        await integration_client.post(f"{BASE}/confirm", json={"token": _token_from(sent[-1])})
    ).json()
    assert (
        await integration_client.get(f"{BASE}/me", headers=_auth(tokens["access_token"]))
    ).status_code == 200

    out = await integration_client.post(
        f"{BASE}/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert out.status_code == 204

    after = await integration_client.get(f"{BASE}/me", headers=_auth(tokens["access_token"]))
    assert after.status_code == 401
    rows = (await db_session.execute(select(MerchantSession))).scalars().all()
    assert [r.revoked_at is not None for r in rows] == [True]


async def test_me_reports_the_operators_own_company(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    token = await _confirmed(integration_client, sent, "me@acme.example.com")

    r = await integration_client.get(f"{BASE}/me", headers=_auth(token))

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "me@acme.example.com"
    assert body["title"] == "ACME Digital"
    assert body["status"] == "active"
    # Nothing has been credited, and a fresh account holds nothing rather than
    # an unknown: the cabinet shows a number from the first screen.
    assert body["balance_usd"] == "0.00"
    assert body["offer_version"]
    assert body["offer_accepted_at"]


async def test_one_operator_never_sees_another_merchant(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """The single rule this whole surface rests on.

    Every cabinet route takes the merchant from the token's subject and never
    from a parameter, so there is no request an operator can shape that reaches
    somebody else's account. This proves the two accounts are actually
    distinct rather than trusting the dependency's docstring.
    """
    first = await _confirmed(integration_client, sent, "a@acme.example.com")
    second = await _confirmed(integration_client, sent, "b@other.example.com")

    one = (await integration_client.get(f"{BASE}/me", headers=_auth(first))).json()
    two = (await integration_client.get(f"{BASE}/me", headers=_auth(second))).json()

    assert one["merchant_id"] != two["merchant_id"]
    assert one["email"] == "a@acme.example.com"
    assert two["email"] == "b@other.example.com"


async def test_a_buyer_token_is_not_a_cabinet_token(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """What the separate ``kind`` buys: a storefront access token presented
    here is rejected by ``verify`` before anything looks up a merchant."""
    from yupay.modules.auth import jwt as authjwt

    buyer = authjwt.mint_access(sub="01a00000-0000-7000-8000-000000000000", sid="s")

    r = await integration_client.get(f"{BASE}/me", headers=_auth(buyer))

    assert r.status_code == 401


def _reset_token_from(mail: dict[str, str]) -> str:
    """The reset link we actually mailed, for the same reason as above."""
    match = re.search(r'href="([^"]+/reset\?token=[^"]+)"', mail["html"])
    assert match is not None, "no reset link in the mail"
    assert match.group(1).startswith(CABINET_URL)
    return parse_qs(urlparse(match.group(1)).query)["token"][0]


async def test_a_reset_link_changes_the_password_and_ends_every_session(
    integration_client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, str]]
) -> None:
    """The point of a reset is "somebody else may have my account".

    Leaving their existing browser signed in would accomplish nothing — the
    attacker's refresh token outlives the password they no longer need — so
    the sessions open at reset time must all be dead afterwards, including the
    one the victim is holding.
    """
    access = await _confirmed(integration_client, sent, "reset@acme.example.com")
    assert (await integration_client.get(f"{BASE}/me", headers=_auth(access))).status_code == 200

    asked = await integration_client.post(
        f"{BASE}/password/forgot", json={"email": "reset@acme.example.com"}
    )
    assert asked.status_code == 204, asked.text
    done = await integration_client.post(
        f"{BASE}/password/reset",
        json={"token": _reset_token_from(sent[-1]), "password": "a-whole-new-secret"},
    )

    assert done.status_code == 200, done.text
    # Signed in on the spot, on a session that is not one of the old ones.
    assert (
        await integration_client.get(f"{BASE}/me", headers=_auth(done.json()["access_token"]))
    ).status_code == 200
    assert (await integration_client.get(f"{BASE}/me", headers=_auth(access))).status_code == 401, (
        "the session held before the reset must be dead"
    )

    old = await integration_client.post(
        f"{BASE}/login", json={"email": "reset@acme.example.com", "password": PASSWORD}
    )
    new = await integration_client.post(
        f"{BASE}/login",
        json={"email": "reset@acme.example.com", "password": "a-whole-new-secret"},
    )
    assert old.status_code == 401
    assert new.status_code == 200


async def test_a_reset_link_works_once(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """A JWT is replayable until it expires; a link that works twice works for
    whoever reads the mailbox second."""
    await _confirmed(integration_client, sent, "once@acme.example.com")
    await integration_client.post(
        f"{BASE}/password/forgot", json={"email": "once@acme.example.com"}
    )
    token = _reset_token_from(sent[-1])

    first = await integration_client.post(
        f"{BASE}/password/reset", json={"token": token, "password": "first-new-secret"}
    )
    second = await integration_client.post(
        f"{BASE}/password/reset", json={"token": token, "password": "second-new-secret"}
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 401
    # And the second password was never set.
    assert (
        await integration_client.post(
            f"{BASE}/login",
            json={"email": "once@acme.example.com", "password": "second-new-secret"},
        )
    ).status_code == 401


async def test_the_mail_endpoints_answer_the_same_to_everyone(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """Registration is open, so neither endpoint may report on a mailbox.

    The four cases that must be indistinguishable from outside — and the three
    of them that must send nothing, which only the mail log shows.
    """
    await _confirmed(integration_client, sent, "live@acme.example.com")
    assert (await _register(integration_client, "pending@acme.example.com")).status_code == 201
    sent.clear()

    answers = [
        await integration_client.post(f"{BASE}/password/forgot", json={"email": address})
        for address in ("live@acme.example.com", "pending@acme.example.com", "no@acme.example.com")
    ] + [
        await integration_client.post(f"{BASE}/confirm/resend", json={"email": address})
        for address in ("live@acme.example.com", "pending@acme.example.com", "no@acme.example.com")
    ]

    assert [r.status_code for r in answers] == [204] * 6
    # Exactly two mails: a reset for the confirmed account, and a confirmation
    # for the one still waiting. An unconfirmed account gets no reset (the
    # link it needs is the confirmation) and a live one gets no second
    # confirmation (anybody knowing the address could otherwise fill that
    # mailbox on demand).
    assert [mail["to"] for mail in sent] == [
        "live@acme.example.com",
        "pending@acme.example.com",
    ]
    assert "/reset?token=" in sent[0]["html"]
    assert "/confirm?token=" in sent[1]["html"]


async def test_a_resent_confirmation_link_actually_confirms(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """The endpoint `login`'s docstring has pointed at since M4 Task 1.

    Before this existed, an operator whose confirmation mail was lost had no
    path at all: registering again answers `email_taken`.
    """
    assert (await _register(integration_client, "lost@acme.example.com")).status_code == 201
    sent.clear()

    assert (
        await integration_client.post(
            f"{BASE}/confirm/resend", json={"email": "lost@acme.example.com"}
        )
    ).status_code == 204
    confirmed = await integration_client.post(
        f"{BASE}/confirm", json={"token": _token_from(sent[-1])}
    )

    assert confirmed.status_code == 200, confirmed.text
    assert (
        await integration_client.post(
            f"{BASE}/login", json={"email": "lost@acme.example.com", "password": PASSWORD}
        )
    ).status_code == 200


async def test_the_confirmation_link_lasts_as_long_as_the_mail_says(
    integration_client: AsyncClient, sent: list[dict[str, str]]
) -> None:
    """The mail promises a day. It used to mean thirty minutes.

    `mint_email_verify` defaults to `jwt_email_token_ttl_seconds` (30 min),
    which is right for a storefront address check and wrong for a registration
    somebody opens when they next read work mail — and
    `merchant_confirm_ttl_seconds` existed, named for exactly this, used only
    as the Redis single-use marker's TTL.
    """
    assert (await _register(integration_client, "ttl@acme.example.com")).status_code == 201
    claims = authjwt.verify(_token_from(sent[-1]), expected_kind="email_verify")

    s = get_settings()
    lifetime = int((claims.exp - claims.iat).total_seconds())
    assert lifetime == s.merchant_confirm_ttl_seconds
    assert lifetime > s.jwt_email_token_ttl_seconds, "the default would be 30 minutes"
