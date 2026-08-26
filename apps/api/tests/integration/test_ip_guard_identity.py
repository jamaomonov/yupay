"""Two dimensions of throttling, because one cannot serve both purposes.

Uzbek mobile carriers put many subscribers behind one public address, so a
per-IP credential limit of ten a minute is a budget strangers spend on each
other: the eleventh genuine sign-in of the minute fails for a whole carrier.
Simply raising it would have loosened brute-force protection sixfold for the
one attacker who really is hammering a single account.

So the IP bucket is raised to a crowd-sized number, and a second, tight bucket
counts attempts against one *identity* — (ip, email) — which is what actually
distinguishes a person mistyping their password from a machine guessing it.
Both must trip; neither alone is a limit worth having.
"""

from __future__ import annotations

import uuid

import pytest
from yupay.core import config as cfg
from yupay.core.redis import get_redis

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _guard_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_IP_GUARD_MAX", "10")
    monkeypatch.setenv("AUTH_IP_GUARD_BUCKET_MAX", '{"login": 40}')
    monkeypatch.setenv("AUTH_IP_GUARD_SUBJECT_MAX", "5")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _ip() -> str:
    return f"203.0.113.{int(uuid.uuid4().hex[:2], 16) % 254 + 1}"


async def _flush(ip: str, *emails: str) -> None:
    from yupay.modules.auth.ip_guard import subject_key

    redis = get_redis()
    await redis.delete(f"auth:ipguard:login:{ip}")
    for email in emails:
        await redis.delete(subject_key("login", ip, email))


async def _login(client, ip: str, email: str) -> int:
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong-password-12"},
        headers={"X-Forwarded-For": ip},
    )
    return r.status_code


async def test_one_account_is_throttled_before_the_ip_budget_is_spent(
    integration_client,
) -> None:
    """The brute-force case: many guesses against a single account."""
    ip, email = _ip(), "victim@example.com"
    await _flush(ip, email)

    statuses = [await _login(integration_client, ip, email) for _ in range(8)]

    assert 429 in statuses, (
        "five guesses against one identity must trip the subject bucket long "
        f"before the 40/min IP budget; got {statuses}"
    )
    await _flush(ip, email)


async def test_neighbours_on_one_carrier_address_do_not_lock_each_other_out(
    integration_client,
) -> None:
    """The reason this exists: six strangers behind one carrier NAT, one
    sign-in each. Under a shared 10/min IP bucket this used to be fine and
    under a per-identity bucket it stays fine — what must not happen is the
    subject bucket being keyed on the IP alone."""
    ip = _ip()
    emails = [f"neighbour{i}@example.com" for i in range(6)]
    await _flush(ip, *emails)

    statuses = [await _login(integration_client, ip, email) for email in emails]

    assert 429 not in statuses, (
        f"six different people behind one address must each get their own budget; got {statuses}"
    )
    await _flush(ip, *emails)


async def test_the_ip_ceiling_still_exists_for_credential_stuffing(
    integration_client,
) -> None:
    """The other attack: one guess each against many accounts. The per-identity
    bucket cannot see it, so the (raised) IP bucket has to."""
    ip = _ip()
    emails = [f"stuffed{i}@example.com" for i in range(45)]
    await _flush(ip, *emails)

    statuses = [await _login(integration_client, ip, email) for email in emails]

    assert 429 in statuses, (
        f"45 attempts from one address against a 40/min IP bucket must trip it; got {statuses[-5:]}"
    )
    await _flush(ip, *emails)


async def test_the_subject_key_does_not_store_the_email(integration_client) -> None:
    """§9: no PII in Redis keys, which are plaintext-visible to MONITOR/SCAN.
    The player-check cache already hashes its player id for the same reason."""
    from yupay.modules.auth.ip_guard import subject_key

    key = subject_key("login", "203.0.113.7", "someone@example.com")
    assert "someone@example.com" not in key
    assert "someone" not in key
