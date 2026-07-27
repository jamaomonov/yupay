"""Guest checkout end-to-end: guest token → order → intent → deliveries.

Covers the ``Guest`` branches of ``_resolve_actor`` in payments and
fulfillment routes (token/email binding, missing email, mismatched email,
foreign order) that only ever ran for ``Bearer`` users in the suite.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
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

pytestmark = pytest.mark.asyncio

GUEST_EMAIL = "guest.buyer@example.com"


@pytest.fixture
async def _seed_sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="games",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug="dota",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Dota 2")],
    )
    product = Product(
        id=new_id(),
        slug="dota-points",
        brand_id=brand.id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Dota Points")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="dota-100",
        denomination="100",
        region="GLOBAL",
        price_usd=Decimal("1.50"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    from yupay.modules.sourcing.models import SkuSourcingRule

    db_session.add(SkuSourcingRule(sku_id=sku.id, mode="force_supplier", supplier_slug="mock"))
    await db_session.commit()
    return sku.id


async def _guest_token(client: AsyncClient, email: str = GUEST_EMAIL) -> str:
    r = await client.post("/api/v1/auth/guest", json={"email": email})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _guest_order(client: AsyncClient, *, token: str, sku_id: str, tag: str) -> str:
    r = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Guest {token}", "Idempotency-Key": f"gp-order-{tag}-padpad"},
        json={
            "currency": "USD",
            "guest_email": GUEST_EMAIL,
            "items": [{"sku_id": sku_id, "qty": 1, "fulfillment_data": {}}],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_guest_pays_and_reads_deliveries(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _guest_token(integration_client)
    order_id = await _guest_order(integration_client, token=token, sku_id=_seed_sku, tag="01")

    intent = await integration_client.post(
        f"/api/v1/payments/intents?email={GUEST_EMAIL}",
        headers={"Authorization": f"Guest {token}", "Idempotency-Key": "gp-intent-01-padpad"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert intent.status_code == 201, intent.text

    wh = await integration_client.post(
        "/api/v1/webhooks/payments/mock",
        content=json.dumps(
            {
                "event_id": "gp_evt_01",
                "payment_id": intent.json()["external_id"],
                "outcome": "succeeded",
            }
        ),
        headers={"content-type": "application/json"},
    )
    assert wh.status_code == 200, wh.text

    deliveries = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Guest {token}", "X-Guest-Email": GUEST_EMAIL},
    )
    assert deliveries.status_code == 200, deliveries.text
    assert len(deliveries.json()["items"]) == 1


async def test_guest_intent_requires_email_param(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _guest_token(integration_client)
    order_id = await _guest_order(integration_client, token=token, sku_id=_seed_sku, tag="02")

    r = await integration_client.post(
        "/api/v1/payments/intents",
        headers={"Authorization": f"Guest {token}", "Idempotency-Key": "gp-intent-02-padpad"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert r.status_code == 422, r.text


async def test_guest_intent_rejects_mismatched_email(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _guest_token(integration_client)
    order_id = await _guest_order(integration_client, token=token, sku_id=_seed_sku, tag="03")

    r = await integration_client.post(
        "/api/v1/payments/intents?email=someone.else@example.com",
        headers={"Authorization": f"Guest {token}", "Idempotency-Key": "gp-intent-03-padpad"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert r.status_code == 401, r.text


async def test_guest_cannot_touch_foreign_order(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    owner_token = await _guest_token(integration_client)
    order_id = await _guest_order(integration_client, token=owner_token, sku_id=_seed_sku, tag="04")

    stranger_email = "other.guest@example.com"
    stranger = await _guest_token(integration_client, email=stranger_email)
    r = await integration_client.post(
        f"/api/v1/payments/intents?email={stranger_email}",
        headers={"Authorization": f"Guest {stranger}", "Idempotency-Key": "gp-intent-04-padpad"},
        json={"order_id": order_id, "provider": "mock"},
    )
    assert r.status_code == 404, r.text

    deliveries = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Guest {stranger}", "X-Guest-Email": stranger_email},
    )
    assert deliveries.status_code == 404, deliveries.text


async def test_guest_deliveries_email_guards(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _guest_token(integration_client)
    order_id = await _guest_order(integration_client, token=token, sku_id=_seed_sku, tag="05")

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Guest {token}"},
    )
    assert r.status_code == 422, r.text

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries",
        headers={"Authorization": f"Guest {token}", "X-Guest-Email": "wrong@example.com"},
    )
    assert r.status_code == 401, r.text


async def test_guest_reads_order_via_email_header(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    """``GET /orders/{id}`` identifies a guest by the ``X-Guest-Email``
    header — the same header ``/deliveries`` uses, not a query param."""
    token = await _guest_token(integration_client)
    order_id = await _guest_order(integration_client, token=token, sku_id=_seed_sku, tag="06")

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Guest {token}", "X-Guest-Email": GUEST_EMAIL},
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == order_id


async def test_guest_order_lookup_requires_email_header(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _guest_token(integration_client)
    order_id = await _guest_order(integration_client, token=token, sku_id=_seed_sku, tag="07")

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Guest {token}"},
    )
    assert r.status_code == 422, r.text


async def test_guest_order_lookup_rejects_mismatched_email_header(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    token = await _guest_token(integration_client)
    order_id = await _guest_order(integration_client, token=token, sku_id=_seed_sku, tag="08")

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Guest {token}", "X-Guest-Email": "wrong@example.com"},
    )
    assert r.status_code == 401, r.text


async def test_guest_order_lookup_ignores_email_query_param(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    """A ``?email=`` query param must not work as a substitute for the
    header — it would land in Caddy / proxy access logs and browser
    history, which is exactly what moving to a header fixes."""
    token = await _guest_token(integration_client)
    order_id = await _guest_order(integration_client, token=token, sku_id=_seed_sku, tag="09")

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}?email={GUEST_EMAIL}",
        headers={"Authorization": f"Guest {token}"},
    )
    assert r.status_code == 422, r.text


async def test_guest_deliveries_ignores_email_query_param(
    integration_client: AsyncClient, _seed_sku: str
) -> None:
    """Same as above for ``/deliveries``: a ``?email=`` query param alone,
    without the ``X-Guest-Email`` header, must not authorise the lookup."""
    token = await _guest_token(integration_client)
    order_id = await _guest_order(integration_client, token=token, sku_id=_seed_sku, tag="10")

    r = await integration_client.get(
        f"/api/v1/orders/{order_id}/deliveries?email={GUEST_EMAIL}",
        headers={"Authorization": f"Guest {token}"},
    )
    assert r.status_code == 422, r.text
