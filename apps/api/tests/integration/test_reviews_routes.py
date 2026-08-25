"""Reviews HTTP routes: submit gate, public list, moderation."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.auth.jwt import mint_access
from yupay.modules.users.models import User

from tests.integration.test_reviews_service import _make_order, _make_user, _seed_brand

pytestmark = pytest.mark.asyncio

_KEY = "idem-abcdef0123456789"


def _token(user_id: str) -> str:
    # current_user only verifies the JWT + Redis blocklist + user row; no
    # auth_sessions lookup, so a freshly minted access token resolves.
    return mint_access(sub=user_id, sid=new_id())


async def _make_admin(db: AsyncSession) -> User:
    admin = User(
        id=new_id(),
        email=None,
        display_name="Admin",
        locale="ru",
        display_currency="USD",
        roles=["admin"],
    )
    db.add(admin)
    await db.flush()
    return admin


async def test_post_review_requires_idempotency_key(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, display_name="Alice")
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_order(db_session, user_id=user.id, sku_id=sku.id)
    await db_session.commit()

    r = await integration_client.post(
        "/api/v1/reviews",
        headers={"Authorization": f"Bearer {_token(user.id)}"},
        json={"order_id": order.id, "brand_slug": brand.slug, "rating": 5, "body": "ok"},
    )
    assert r.status_code == 422


async def test_post_then_public_list_shows_it(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, display_name="Alice")
    brand, sku = await _seed_brand(db_session, "pubg")
    order = await _make_order(db_session, user_id=user.id, sku_id=sku.id)
    await db_session.commit()

    r = await integration_client.post(
        "/api/v1/reviews",
        headers={"Authorization": f"Bearer {_token(user.id)}", "Idempotency-Key": _KEY},
        json={"order_id": order.id, "brand_slug": brand.slug, "rating": 4, "body": "good"},
    )
    assert r.status_code == 201, r.text

    lst = await integration_client.get(f"/api/v1/reviews/brands/{brand.slug}")
    body = lst.json()
    assert body["stats"]["count"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["author_name"] == "Alice"  # display_name, never email


async def test_guest_cannot_post(integration_client: AsyncClient, db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    brand, sku = await _seed_brand(db_session, "mlbb")
    order = await _make_order(db_session, user_id=user.id, sku_id=sku.id)
    await db_session.commit()

    r = await integration_client.post(
        "/api/v1/reviews",
        headers={"Idempotency-Key": _KEY},
        json={"order_id": order.id, "brand_slug": brand.slug, "rating": 4},
    )
    assert r.status_code == 401


async def test_duplicate_review_conflicts(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, display_name="Bob")
    brand, sku = await _seed_brand(db_session, "roblox")
    order = await _make_order(db_session, user_id=user.id, sku_id=sku.id)
    await db_session.commit()
    headers = {"Authorization": f"Bearer {_token(user.id)}", "Idempotency-Key": _KEY}
    payload = {"order_id": order.id, "brand_slug": brand.slug, "rating": 5}

    first = await integration_client.post("/api/v1/reviews", headers=headers, json=payload)
    assert first.status_code == 201
    second = await integration_client.post("/api/v1/reviews", headers=headers, json=payload)
    assert second.status_code == 409
    assert second.json()["code"] == "already_reviewed"


async def test_admin_hide_removes_from_public_list(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    buyer = await _make_user(db_session, display_name="Carol")
    admin = await _make_admin(db_session)
    brand, sku = await _seed_brand(db_session, "genshin")
    order = await _make_order(db_session, user_id=buyer.id, sku_id=sku.id)
    await db_session.commit()

    posted = await integration_client.post(
        "/api/v1/reviews",
        headers={"Authorization": f"Bearer {_token(buyer.id)}", "Idempotency-Key": _KEY},
        json={"order_id": order.id, "brand_slug": brand.slug, "rating": 5},
    )
    review_id = posted.json()["id"]

    hidden = await integration_client.post(
        f"/api/v1/admin/reviews/{review_id}/hide",
        headers={
            "Authorization": f"Bearer {_token(admin.id)}",
            "Idempotency-Key": "hide-0123456789ab",
        },
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["status"] == "hidden"

    lst = await integration_client.get(f"/api/v1/reviews/brands/{brand.slug}")
    assert lst.json()["stats"]["count"] == 0


async def test_admin_list_requires_admin(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    plain = await _make_user(db_session)
    await db_session.commit()
    r = await integration_client.get(
        "/api/v1/admin/reviews", headers={"Authorization": f"Bearer {_token(plain.id)}"}
    )
    assert r.status_code == 403


async def _guest_token(client: AsyncClient, email: str) -> str:
    r = await client.post("/api/v1/auth/guest", json={"email": email})
    assert r.status_code == 200
    return r.json()["access_token"]


async def test_guest_can_post_and_list_shows_anonymous(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    from tests.integration.test_reviews_service import _make_guest_order

    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    await db_session.commit()
    token = await _guest_token(integration_client, "g@x.com")
    r = await integration_client.post(
        "/api/v1/reviews",
        headers={
            "Authorization": f"Guest {token}",
            "X-Guest-Email": "g@x.com",
            "Idempotency-Key": _KEY,
        },
        json={"order_id": order.id, "brand_slug": "steam", "rating": 5, "body": "fast"},
    )
    assert r.status_code == 201
    assert r.json()["author_name"] is None
    lst = await integration_client.get("/api/v1/reviews/brands/steam")
    assert lst.json()["stats"]["count"] == 1


async def test_guest_wrong_email_rejected(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    from tests.integration.test_reviews_service import _make_guest_order

    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    await db_session.commit()
    token = await _guest_token(integration_client, "g@x.com")
    r = await integration_client.post(
        "/api/v1/reviews",
        headers={
            "Authorization": f"Guest {token}",
            "X-Guest-Email": "evil@x.com",
            "Idempotency-Key": _KEY,
        },
        json={"order_id": order.id, "brand_slug": "steam", "rating": 5},
    )
    assert r.status_code == 401


async def test_eligibility_guest_delivered_then_reviewed(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    from tests.integration.test_reviews_service import _make_guest_order

    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="g@x.com", sku_id=sku.id)
    await db_session.commit()
    token = await _guest_token(integration_client, "g@x.com")
    h = {"Authorization": f"Guest {token}", "X-Guest-Email": "g@x.com"}
    e1 = await integration_client.get(f"/api/v1/reviews/eligibility?order_id={order.id}", headers=h)
    assert e1.json() == {"brand_slug": "steam", "delivered": True, "already_reviewed": False}
    await integration_client.post(
        "/api/v1/reviews",
        headers={**h, "Idempotency-Key": _KEY},
        json={"order_id": order.id, "brand_slug": "steam", "rating": 5},
    )
    e2 = await integration_client.get(f"/api/v1/reviews/eligibility?order_id={order.id}", headers=h)
    assert e2.json()["already_reviewed"] is True


async def test_eligibility_wrong_user_forbidden(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session, display_name="Owner")
    stranger = await _make_user(db_session, display_name="Stranger")
    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_order(db_session, user_id=owner.id, sku_id=sku.id)
    await db_session.commit()

    r = await integration_client.get(
        f"/api/v1/reviews/eligibility?order_id={order.id}",
        headers={"Authorization": f"Bearer {_token(stranger.id)}"},
    )
    assert r.status_code == 403


async def test_eligibility_wrong_guest_forbidden(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    from tests.integration.test_reviews_service import _make_guest_order

    brand, sku = await _seed_brand(db_session, "steam")
    order = await _make_guest_order(db_session, guest_email="owner@x.com", sku_id=sku.id)
    await db_session.commit()
    # This guest's token + X-Guest-Email are internally consistent (so
    # resolve_request_actor accepts them, unlike test_guest_wrong_email_rejected's
    # mismatched pair) but belong to a different guest than the order's
    # guest_email — that's what should trip the ownership check, not auth.
    token = await _guest_token(integration_client, "someone-else@x.com")
    r = await integration_client.get(
        f"/api/v1/reviews/eligibility?order_id={order.id}",
        headers={"Authorization": f"Guest {token}", "X-Guest-Email": "someone-else@x.com"},
    )
    assert r.status_code == 403


async def test_the_queue_carries_names_not_just_ids(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The moderation queue used to hand the panel three bare UUIDs.

    Brand, order and author were ids, so an operator had to open each one to
    find out what the row was about. Resolving them in the query that already
    touches these tables is one join instead of a page of round trips.
    """
    buyer = await _make_user(db_session, display_name="Дарья")
    admin = await _make_admin(db_session)
    brand, sku = await _seed_brand(db_session, "oxide-q")
    brand.logo_url = "https://cdn.example/oxide.png"
    order = await _make_order(db_session, user_id=buyer.id, sku_id=sku.id)
    await db_session.commit()

    await integration_client.post(
        "/api/v1/reviews",
        headers={"Authorization": f"Bearer {_token(buyer.id)}", "Idempotency-Key": _KEY},
        json={"order_id": order.id, "brand_slug": brand.slug, "rating": 5},
    )

    r = await integration_client.get(
        "/api/v1/admin/reviews", headers={"Authorization": f"Bearer {_token(admin.id)}"}
    )
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["items"] if x["order_id"] == order.id)
    assert row["brand_slug"] == brand.slug
    assert row["brand_name"] == "Oxide-Q"
    assert row["brand_logo_url"] == "https://cdn.example/oxide.png"
    # The author is a signed-in customer, so the panel labels them by name.
    assert row["user_name"] == "Дарья"
    assert row["guest_email"] is None


async def test_a_guest_review_is_labelled_as_a_guest(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Exactly one of ``user_name`` / ``guest_email`` is set on every row.

    That is what lets the panel say "гость" honestly instead of printing an
    address that looks like an account.
    """
    admin = await _make_admin(db_session)
    brand, sku = await _seed_brand(db_session, "oxide-g")
    email = "guest@example.com"
    from tests.integration.test_reviews_service import _make_guest_order

    order = await _make_guest_order(db_session, guest_email=email, sku_id=sku.id)
    await db_session.commit()

    token = await _guest_token(integration_client, email)
    posted = await integration_client.post(
        "/api/v1/reviews",
        headers={
            "Authorization": f"Guest {token}",
            "X-Guest-Email": email,
            "Idempotency-Key": "guest-key-0123456",
        },
        json={"order_id": order.id, "brand_slug": brand.slug, "rating": 4},
    )
    assert posted.status_code == 201, posted.text

    r = await integration_client.get(
        "/api/v1/admin/reviews", headers={"Authorization": f"Bearer {_token(admin.id)}"}
    )
    row = next(x for x in r.json()["items"] if x["order_id"] == order.id)
    assert row["user_id"] is None
    assert row["user_name"] is None
    assert row["guest_email"] == email


async def test_brand_rollup_counts_every_review_not_just_the_page(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The by-brand block is aggregated in SQL on purpose.

    The queue is capped at 200 rows; counting on the client would describe that
    slice as if it were all of them, and this is the number an operator uses to
    decide which brand to open.
    """
    admin = await _make_admin(db_session)
    brand, sku = await _seed_brand(db_session, "oxide-s")
    for i, rating in enumerate((5, 3)):
        buyer = await _make_user(db_session, display_name=f"B{i}")
        order = await _make_order(db_session, user_id=buyer.id, sku_id=sku.id)
        await db_session.commit()
        await integration_client.post(
            "/api/v1/reviews",
            headers={
                "Authorization": f"Bearer {_token(buyer.id)}",
                "Idempotency-Key": f"stats-key-{i}-0123",
            },
            json={"order_id": order.id, "brand_slug": brand.slug, "rating": rating},
        )

    r = await integration_client.get(
        "/api/v1/admin/reviews/by-brand",
        headers={"Authorization": f"Bearer {_token(admin.id)}"},
    )
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["items"] if x["brand_slug"] == brand.slug)
    assert row["total"] == 2
    assert row["avg_rating"] == 4.0
    assert row["reported"] == 0
    assert row["brand_name"] == "Oxide-S"


async def test_the_queue_can_be_narrowed_to_one_brand(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The by-brand block asks the server, not the loaded page.

    The queue is capped, so filtering client-side would show whichever of a
    brand's reviews happened to fit in the last N rows and call that all of
    them — under the brand's own heading, which is where an operator trusts the
    number most.
    """
    admin = await _make_admin(db_session)
    mine, mine_sku = await _seed_brand(db_session, "oxide-mine")
    other, other_sku = await _seed_brand(db_session, "oxide-other")

    ids: dict[str, str] = {}
    for key, brand, sku in (("mine", mine, mine_sku), ("other", other, other_sku)):
        buyer = await _make_user(db_session, display_name=f"U-{key}")
        order = await _make_order(db_session, user_id=buyer.id, sku_id=sku.id)
        await db_session.commit()
        posted = await integration_client.post(
            "/api/v1/reviews",
            headers={
                "Authorization": f"Bearer {_token(buyer.id)}",
                "Idempotency-Key": f"brandfilter-{key}-01",
            },
            json={"order_id": order.id, "brand_slug": brand.slug, "rating": 5},
        )
        assert posted.status_code == 201, posted.text
        ids[key] = posted.json()["id"]

    r = await integration_client.get(
        f"/api/v1/admin/reviews?brand={mine.slug}",
        headers={"Authorization": f"Bearer {_token(admin.id)}"},
    )
    assert r.status_code == 200, r.text
    got = {x["id"] for x in r.json()["items"]}
    assert ids["mine"] in got
    assert ids["other"] not in got
    # The total describes the brand, not the page it was sliced from.
    assert r.json()["total"] == 1
