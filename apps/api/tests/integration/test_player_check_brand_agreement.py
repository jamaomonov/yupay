"""``brand_check_field`` against a real brand with two active products.

Companion to the pure-function tests in ``tests/unit/test_player_check_service.py``
(``_agreed_field`` on bare dicts, no DB) and to the endpoint-level ambiguity
cases in ``test_player_check_endpoint.py`` (two products mapped to different
*games*). This file exercises the trap ADR-0079 exists to name: a **second
product added to a brand that already has a check-bearing one**. Written for
Task 4 of the NOVA/Free Fire work — ``free-fire-packs`` joins ``free-fire``
beside ``free-fire-diamonds``, and the seed script that creates it copies
``required_fields`` verbatim for exactly this reason. See
``docs/superpowers/specs/2026-09-17-nova-steam-and-free-fire-design.md`` §5.

Both cases need a real ``AsyncSession`` and a real SQL query —
``brand_check_field`` joins ``Product`` and filters ``active``, which a
hand-built list of dicts cannot stand in for.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
import structlog.testing
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
)
from yupay.modules.integrations import player_check as pc

pytestmark = pytest.mark.integration

#: The field `free-fire-diamonds` actually carries in production (see
#: `scripts/seed/2026-08-20_enable_free_fire_player_check.sql`): a g2b check
#: with no server field.
_CHECK_FIELD: dict[str, Any] = {
    "key": "player_id",
    "label": {"ru": "ID игрока", "en": "Player ID", "uz": "Oʻyinchi ID"},
    "type": "text",
    "pattern": "^[0-9]{6,20}$",
    "required": True,
    "check": {"provider": "g2b", "server_field": None},
}


async def _seed_brand(db_session: AsyncSession, *, slug: str) -> Brand:
    """A fresh category + brand, committed, ready for products to be added."""
    category = Category(
        id=new_id(),
        slug=f"{slug}-category",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Игры")],
    )
    brand = Brand(
        id=new_id(),
        slug=slug,
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Test Brand")],
    )
    db_session.add_all([category, brand])
    await db_session.commit()
    return brand


def _product(*, brand_id: str, slug: str, required_fields: list[dict[str, Any]]) -> Product:
    """An unsaved active `top_up` product carrying the given form fields."""
    return Product(
        id=new_id(),
        slug=slug,
        brand_id=brand_id,
        kind="top_up",
        sort_order=10,
        active=True,
        required_fields=required_fields,
        translations=[ProductTranslation(locale="ru", name=slug)],
    )


async def test_brand_check_field_survives_a_second_product_with_the_same_check(
    db_session: AsyncSession,
) -> None:
    """A second active product whose `required_fields` is a verbatim copy of
    the first's must not disable the brand's check — the property the seed
    script's "read it from the database, never retype it" rule exists to
    protect (ADR-0079)."""
    brand = await _seed_brand(db_session, slug="ff-agreement-same")
    first = _product(
        brand_id=brand.id, slug="ff-agreement-same-diamonds", required_fields=[_CHECK_FIELD]
    )
    # A *copy*, not the same object — exactly what the seed script writes:
    # `free-fire-packs` gets its own JSONB value equal in content to
    # `free-fire-diamonds`'s, not a shared reference.
    second = _product(
        brand_id=brand.id,
        slug="ff-agreement-same-packs",
        required_fields=copy.deepcopy([_CHECK_FIELD]),
    )
    db_session.add_all([first, second])
    await db_session.commit()

    field = await pc.brand_check_field(db_session, brand.id)

    assert field is not None
    assert field["check"] == {"provider": "g2b", "server_field": None}
    assert field["key"] == "player_id"


async def test_brand_check_field_none_and_logs_when_the_copy_disagrees(
    db_session: AsyncSession,
) -> None:
    """The trap this task walks past: a second product whose check config
    differs — even by one field the matcher reads — must turn the brand's
    check off entirely, and say why in the logs rather than silently guessing
    which product is right."""
    brand = await _seed_brand(db_session, slug="ff-agreement-diff")
    first = _product(
        brand_id=brand.id, slug="ff-agreement-diff-diamonds", required_fields=[_CHECK_FIELD]
    )
    drifted = copy.deepcopy(_CHECK_FIELD)
    drifted["check"]["server_field"] = "server_id"  # the one field flipped
    second = _product(
        brand_id=brand.id, slug="ff-agreement-diff-packs", required_fields=[drifted]
    )
    db_session.add_all([first, second])
    await db_session.commit()

    with structlog.testing.capture_logs() as logs:
        field = await pc.brand_check_field(db_session, brand.id)

    assert field is None
    mismatches = [e for e in logs if e["event"] == "player_check_brand_config_mismatch"]
    assert len(mismatches) == 1
    assert mismatches[0]["brand_id"] == brand.id
