"""Chargeback evidence capture (ADR-0044).

Runs against a real Postgres because the two things worth proving here are
database behaviours: that a capture which fails at the SQL layer is confined to
its savepoint and does not take the order down with it, and that INET/JSONB
round-trip what we claim to be storing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
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
from yupay.modules.evidence.models import OrderEvidence
from yupay.modules.evidence.schemas import ClientHints
from yupay.modules.evidence.service import device_hash, ip_country_from, purge_expired
from yupay.modules.orders.models import Order
from yupay.modules.users.models import TelegramLink, User

#: Must match TELEGRAM_BOT_TOKEN in the test env (tests/conftest.py).
BOT_TOKEN = "123456:TEST"


def _sign_init_data(fields: dict[str, str]) -> str:
    pairs = sorted((k, v) for k, v in fields.items() if k != "hash")
    data = "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    fields = {**fields, "hash": hmac.new(secret, data, hashlib.sha256).hexdigest()}
    return urlencode(fields)


async def _login_user(client: AsyncClient, tg_id: int) -> str:
    user_json = json.dumps({"id": tg_id, "first_name": "U"}, separators=(",", ":"))
    init = _sign_init_data({"user": user_json, "auth_date": str(int(time.time()))})
    r = await client.post("/api/v1/auth/telegram/webapp", json={"init_data": init})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _grant_admin(db: AsyncSession, tg_id: int) -> None:
    user_id = (
        await db.execute(
            select(User.id)
            .join(TelegramLink, TelegramLink.user_id == User.id)
            .where(TelegramLink.tg_user_id == tg_id)
        )
    ).scalar_one()
    await db.execute(update(User).where(User.id == user_id).values(roles=["admin"]))
    await db.commit()


@pytest.fixture
async def _seed_sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="ev-cat",
        sort_order=1,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Ev")],
    )
    brand = Brand(
        id=new_id(),
        category_id=category.id,
        slug="ev-brand",
        sort_order=1,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Ev Brand")],
    )
    product = Product(
        id=new_id(),
        brand_id=brand.id,
        slug="ev-prod",
        kind="top_up",
        sort_order=1,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Ev Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="EV-1",
        denomination="1",
        region="GLOBAL",
        price_usd=Decimal("1.50"),
        sort_order=1,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return sku.id


async def _post_order(
    client: AsyncClient,
    *,
    token: str,
    sku_id: str,
    key: str,
    forwarded_for: str = "203.0.113.7, 10.0.0.2",
    hints: dict[str, str] | None = None,
    country: str | None = None,
) -> tuple[int, str]:
    body: dict[str, object] = {
        "currency": "USD",
        "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}],
    }
    if hints is not None:
        body["client_hints"] = hints
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": key,
        "X-Forwarded-For": forwarded_for,
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7)",
        "Accept-Language": "ru-RU,ru;q=0.9",
    }
    if country is not None:
        headers["cf-ipcountry"] = country
    r = await client.post("/api/v1/orders", headers=headers, json=body)
    return r.status_code, r.json().get("id", "")


# ---------- device_hash ----------


def test_device_hash_is_stable_and_component_sensitive() -> None:
    hints = ClientHints(timezone="Europe/Kiev", locale="uk-UA", screen="2560x1440@1")
    a = device_hash("Mozilla/5.0", hints)
    assert a == device_hash("Mozilla/5.0", hints)  # deterministic
    assert a != device_hash(
        "Mozilla/5.0", ClientHints(timezone="Asia/Tashkent", locale="uk-UA", screen="2560x1440@1")
    )
    assert a is not None
    assert len(a) == 64


def test_device_hash_of_nothing_is_none() -> None:
    # An evidence row with no UA and no hints must not produce a shared
    # "empty" fingerprint that links every unknown device into one identity.
    assert device_hash(None, None) is None
    assert device_hash("", ClientHints()) is None


# ---------- ip_country_from ----------


def test_ip_country_normalises_and_rejects_junk() -> None:
    assert ip_country_from("uz") == "UZ"
    assert ip_country_from("T1") == "T1"  # Tor sentinel is a signal, keep it
    assert ip_country_from("XX") == "XX"  # CF unknown sentinel, kept as-is
    assert ip_country_from(None) is None
    assert ip_country_from("") is None
    assert ip_country_from("USA") is None  # only two ASCII letters/digits
    assert ip_country_from("<script>") is None


# ---------- capture ----------


async def test_capture_records_the_request_context(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=9101)
    status, order_id = await _post_order(
        integration_client,
        token=token,
        sku_id=_seed_sku,
        key="idem-evidence-9101-pad",
        hints={"timezone": "Asia/Tashkent", "locale": "ru-RU", "screen": "412x915@2.6"},
    )
    assert status == 201

    row = (
        await db_session.execute(select(OrderEvidence).where(OrderEvidence.order_id == order_id))
    ).scalar_one()

    # The leftmost forwarded entry, not our own proxy hop.
    assert row.ip == "203.0.113.7"
    assert row.user_agent is not None
    assert "Pixel 7" in row.user_agent
    assert row.accept_language == "ru-RU,ru;q=0.9"
    assert row.client_hints["timezone"] == "Asia/Tashkent"
    # An unreported signal is absent from the record rather than stored as a
    # null, so a pack shows what the browser actually said.
    assert set(row.client_hints) == {"timezone", "locale", "screen"}
    assert row.purge_after > now()
    # The stored fingerprint must be derivable from the stored UA + hints —
    # not merely present — or a later query joining on it silently drifts
    # from what capture actually wrote.
    assert row.device_hash == device_hash(row.user_agent, ClientHints(**row.client_hints))


async def test_capture_survives_a_client_that_sends_no_hints(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=9102)
    status, order_id = await _post_order(
        integration_client, token=token, sku_id=_seed_sku, key="idem-evidence-9102-pad"
    )
    assert status == 201
    row = (
        await db_session.execute(select(OrderEvidence).where(OrderEvidence.order_id == order_id))
    ).scalar_one()
    assert row.client_hints == {}
    assert row.ip == "203.0.113.7"


async def test_capture_records_ip_country_and_the_pack_carries_it(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    """Cloudflare's ``cf-ipcountry`` header becomes the row's ``ip_country``.

    This is the raw signal the pre-charge geo veto (a later task) will read off
    this table, so both the write and the admin-facing read must carry it.
    """
    token = await _login_user(integration_client, tg_id=9109)
    status, order_id = await _post_order(
        integration_client,
        token=token,
        sku_id=_seed_sku,
        key="idem-evidence-9109-pad",
        country="uz",  # lower-case on the wire, stored upper-cased; home country, so
        # a zero-delivery signed-in buyer still clears the pre-charge veto (ADR-0063)
        # — this test is about capture + upper-casing, not geography.
    )
    assert status == 201

    row = (
        await db_session.execute(select(OrderEvidence).where(OrderEvidence.order_id == order_id))
    ).scalar_one()
    assert row.ip_country == "UZ"

    await _grant_admin(db_session, tg_id=9109)
    admin_token = await _login_user(integration_client, tg_id=9109)
    r = await integration_client.get(
        f"/api/v1/admin/orders/{order_id}/evidence",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["capture"]["ip_country"] == "UZ"


async def test_a_failed_capture_does_not_cost_us_the_order(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    _seed_sku: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of the savepoint.

    Forces a database-level failure inside the capture — an address Postgres
    refuses to cast to INET. Without the nested transaction this poisons the
    request's transaction and the order is lost at commit, turning a safeguard
    into an outage.
    """
    from yupay.modules.evidence import service as ev_svc

    monkeypatch.setattr(ev_svc, "_normalised_ip", lambda _request: "999.999.999.999")

    token = await _login_user(integration_client, tg_id=9103)
    status, order_id = await _post_order(
        integration_client, token=token, sku_id=_seed_sku, key="idem-evidence-9103-pad"
    )

    assert status == 201, "the sale must go through even when evidence cannot be written"
    order = (
        await db_session.execute(select(Order).where(Order.id == order_id))
    ).scalar_one_or_none()
    assert order is not None, "the order must be committed, not rolled back with the capture"
    missing = (
        await db_session.execute(select(OrderEvidence).where(OrderEvidence.order_id == order_id))
    ).scalar_one_or_none()
    assert missing is None, "a failed capture leaves a gap in the pack, not a partial row"


async def test_a_retried_order_keeps_the_original_context(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    """A retry can arrive from a different network than the purchase did.

    The context worth defending is the one the order was actually placed under,
    so the first capture wins and the retry must not overwrite it.
    """
    token = await _login_user(integration_client, tg_id=9104)
    key = "idem-evidence-9104-pad"
    first_status, order_id = await _post_order(
        integration_client, token=token, sku_id=_seed_sku, key=key, forwarded_for="203.0.113.7"
    )
    assert first_status == 201

    retry_status, retry_id = await _post_order(
        integration_client, token=token, sku_id=_seed_sku, key=key, forwarded_for="198.51.100.99"
    )
    assert retry_id == order_id, "same key must return the same order"
    assert retry_status in (200, 201)

    rows = (
        (await db_session.execute(select(OrderEvidence).where(OrderEvidence.order_id == order_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].ip == "203.0.113.7"


# ---------- retention ----------


async def test_purge_deletes_only_what_is_past_its_stamped_date(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    token = await _login_user(integration_client, tg_id=9105)
    _, keep_id = await _post_order(
        integration_client, token=token, sku_id=_seed_sku, key="idem-evidence-9105-pad"
    )
    _, drop_id = await _post_order(
        integration_client, token=token, sku_id=_seed_sku, key="idem-evidence-9105b-pad"
    )

    expired = (
        await db_session.execute(select(OrderEvidence).where(OrderEvidence.order_id == drop_id))
    ).scalar_one()
    expired.purge_after = now() - timedelta(days=1)
    await db_session.commit()

    deleted = await purge_expired(db_session)
    await db_session.commit()

    assert deleted == 1
    remaining = (await db_session.execute(select(OrderEvidence.order_id))).scalars().all()
    assert keep_id in remaining
    assert drop_id not in remaining


# ---------- admin pack ----------


async def test_the_pack_is_admin_only(integration_client: AsyncClient, _seed_sku: str) -> None:
    """The one endpoint that returns an unhashed IP must not answer a customer."""
    token = await _login_user(integration_client, tg_id=9106)
    _, order_id = await _post_order(
        integration_client, token=token, sku_id=_seed_sku, key="idem-evidence-9106-pad"
    )

    anon = await integration_client.get(f"/api/v1/admin/orders/{order_id}/evidence")
    assert anon.status_code in (401, 403)

    as_customer = await integration_client.get(
        f"/api/v1/admin/orders/{order_id}/evidence",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert as_customer.status_code == 403


async def test_an_admin_gets_a_usable_pack(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    """Serialisation is the point here, not authorisation.

    The IP column is INET and asyncpg returns ``ipaddress`` objects for it, so
    a route typed against ``str`` blows up at response time while type-checking
    clean. Only an end-to-end fetch catches that.
    """
    token = await _login_user(integration_client, tg_id=9107)
    _, order_id = await _post_order(
        integration_client,
        token=token,
        sku_id=_seed_sku,
        key="idem-evidence-9107-pad",
        hints={"timezone": "Asia/Tashkent"},
    )
    await _grant_admin(db_session, tg_id=9107)
    admin_token = await _login_user(integration_client, tg_id=9107)

    r = await integration_client.get(
        f"/api/v1/admin/orders/{order_id}/evidence",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    pack = r.json()
    assert pack["capture"]["ip"] == "203.0.113.7"
    assert pack["capture"]["client_hints"]["timezone"] == "Asia/Tashkent"
    # The timeline is what answers "when was this delivered, and to whom".
    assert isinstance(pack["timeline"], list)
    assert pack["timeline"]


async def test_reading_the_pack_is_written_to_the_order_timeline(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    """Looking up a customer's address has to leave a trace.

    This is the only route in the API that returns an unhashed IP, so the read
    is audited the same way a delivery-artifact read is. The event must not
    land inside the pack itself, though: that goes to an acquirer, and our own
    access log is not part of their answer.
    """
    token = await _login_user(integration_client, tg_id=9108)
    _, order_id = await _post_order(
        integration_client, token=token, sku_id=_seed_sku, key="idem-evidence-9108-pad"
    )
    await _grant_admin(db_session, tg_id=9108)
    admin_token = await _login_user(integration_client, tg_id=9108)

    r = await integration_client.get(
        f"/api/v1/admin/orders/{order_id}/evidence",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    assert not [e for e in r.json()["timeline"] if e["kind"] == "admin.evidence_viewed"]

    # The next read sees the previous one, which is the point of recording it.
    again = await integration_client.get(
        f"/api/v1/admin/orders/{order_id}/evidence",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert again.status_code == 200, again.text
    viewed = [e for e in again.json()["timeline"] if e["kind"] == "admin.evidence_viewed"]
    assert len(viewed) == 1
    assert viewed[0]["actor"].startswith("admin:")
    assert viewed[0]["payload"] == {"has_capture": True}


async def test_a_deposit_records_the_request_context_too(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A wallet deposit is an order, and it reached the evidence panel empty.

    ``POST /wallet/topup`` builds its order in its own service and never called
    ``capture_for_order``, so every deposit showed the admin "контекст не
    записан". A deposit needs the pack more than a sale does, not less: there
    are no goods, no delivery and no player id to point at, so the request
    context is most of what an acquirer can be shown.
    """
    token = await _login_user(integration_client, tg_id=9151)
    r = await integration_client.post(
        "/api/v1/wallet/topup",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "idem-evidence-topup-01",
            "X-Yupay-Surface": "miniapp",
            "X-Forwarded-For": "203.0.113.9, 10.0.0.2",
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7)",
            "Accept-Language": "ru-RU,ru;q=0.9",
        },
        json={
            "amount": "50000",
            "provider": "mock",
            "client_hints": {"timezone": "Asia/Tashkent", "locale": "ru-RU"},
        },
    )
    assert r.status_code == 201, r.text
    order_id = r.json()["order_id"]

    row = (
        await db_session.execute(select(OrderEvidence).where(OrderEvidence.order_id == order_id))
    ).scalar_one()
    # The leftmost forwarded entry, not our own proxy hop — same as a sale.
    assert row.ip == "203.0.113.9"
    assert row.accept_language == "ru-RU,ru;q=0.9"
    assert row.client_hints["timezone"] == "Asia/Tashkent"


# ---------- migration 0059 backfill ----------

#: The exact statement migration 0059 runs to backfill pre-existing rows.
#: Kept identical here so a divergence between the two is caught by this test
#: rather than discovered against production data.
_BACKFILL_SQL = text(
    """
    UPDATE order_evidence SET device_hash = encode(digest(
        coalesce(user_agent, '') || '|' ||
        coalesce(client_hints->>'timezone', '') || '|' ||
        coalesce(client_hints->>'locale', '') || '|' ||
        coalesce(client_hints->>'screen', ''), 'sha256'), 'hex')
    WHERE coalesce(user_agent, '') || coalesce(client_hints->>'timezone', '')
          || coalesce(client_hints->>'locale', '') || coalesce(client_hints->>'screen', '') <> ''
    """
)


async def test_backfill_sql_matches_the_python_helper(
    integration_client: AsyncClient, db_session: AsyncSession, _seed_sku: str
) -> None:
    """Migration 0059's SQL backfill must byte-for-byte match ``device_hash``.

    If the UPDATE statement joined components in a different order, or used a
    different empty-string convention, than the Python helper, a device seen
    before the migration and the same device seen after it would silently
    become two different fingerprints.
    """
    token = await _login_user(integration_client, tg_id=9161)
    _, order_id = await _post_order(
        integration_client,
        token=token,
        sku_id=_seed_sku,
        key="idem-evidence-9161-pad",
        hints={"timezone": "Asia/Tashkent", "locale": "ru-RU", "screen": "412x915@2.6"},
    )

    # Simulate the pre-migration state: capture already ran (0059 not applied
    # yet in spirit), so device_hash is unset.
    await db_session.execute(
        update(OrderEvidence).where(OrderEvidence.order_id == order_id).values(device_hash=None)
    )
    await db_session.commit()

    await db_session.execute(_BACKFILL_SQL)
    await db_session.commit()

    row = (
        await db_session.execute(select(OrderEvidence).where(OrderEvidence.order_id == order_id))
    ).scalar_one()
    expected = device_hash(row.user_agent, ClientHints(**row.client_hints))
    assert row.device_hash == expected
    assert row.device_hash is not None
