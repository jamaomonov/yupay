"""Catalog: per-surface visibility (``visible_b2b``) and per-SKU B2B markup.

The merchant B2B catalog needs its own visibility gate, independent of retail.
``active`` on :class:`~yupay.modules.catalog.models.Brand` and
:class:`~yupay.modules.catalog.models.Sku` keeps its exact existing meaning —
retail visibility, untouched by this migration. ``visible_b2b`` is the new,
separate merchant-catalog gate on both models; effective B2B visibility is
``brand.visible_b2b AND sku.visible_b2b`` (spec
``docs/superpowers/specs/2026-09-06-merchant-b2b-design.md`` §6). ``skus``
also grows ``b2b_markup_pct`` (spec §8.3): the per-SKU wholesale markup over
``cost_usdt``, uniform across every merchant, default 7%, admin-edited.

Launch data flip: every currently **active** SKU whose product is
``active`` and of ``kind IN ('top_up', 'voucher')`` and whose brand is
**active** flips to ``visible_b2b = true`` — except brands in the
``gift-cards`` category (Discord, Roblox, Standoff 2 Gold: personal
redeemable gift codes, not wholesale top-up/voucher stock) and the
``steam-gifts`` brand (a personalised gift for someone else's account,
``kind='top_up'`` at the catalog level but not a wholesale line either — see
``scripts/seed/2026-09-03_steam_gifts.py``). A brand then flips to
``visible_b2b = true`` only if at least one of its SKUs was flipped, so a
brand that mixes eligible and excluded/inactive lines is not blanket-flipped.

No CHECK constraint is added on ``b2b_markup_pct``: the spec's "margin floor"
guard (§8.3) is an application-level rejection at order time, not a DB
invariant, and the interface asked for here is exactly ``Numeric(5,2) NOT
NULL DEFAULT 7`` — nothing more.

Revision ID: 0068_catalog_b2b_flags
Revises: 0067_wallet_merchant_deposit
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0068_catalog_b2b_flags"
down_revision: str | None = "0067_wallet_merchant_deposit"
branch_labels: str | None = None
depends_on: str | None = None

#: Brands that are structurally kind IN ('top_up', 'voucher') at the catalog
#: level but are launch-excluded from the B2B catalog by identity, not kind.
_EXCLUDED_BRAND_SLUGS = ("steam-gifts",)
_EXCLUDED_BRAND_SLUGS_SQL = ", ".join(repr(slug) for slug in _EXCLUDED_BRAND_SLUGS)


def upgrade() -> None:
    op.add_column(
        "brands",
        sa.Column("visible_b2b", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "skus",
        sa.Column("visible_b2b", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "skus",
        sa.Column("b2b_markup_pct", sa.Numeric(5, 2), nullable=False, server_default="7"),
    )

    # Flip eligible SKUs first — this is the single place the eligibility rule
    # lives. The brand flip below then just asks "did any of my SKUs flip?".
    op.execute(
        f"""
        UPDATE skus
        SET visible_b2b = true
        FROM products, brands
        WHERE skus.product_id = products.id
          AND products.brand_id = brands.id
          AND skus.active
          AND products.active
          AND products.kind IN ('top_up', 'voucher')
          AND brands.active
          AND brands.slug NOT IN ({_EXCLUDED_BRAND_SLUGS_SQL})
          AND brands.category_id NOT IN (
              SELECT id FROM categories WHERE slug = 'gift-cards'
          )
        """
    )
    op.execute(
        """
        UPDATE brands
        SET visible_b2b = true
        WHERE EXISTS (
            SELECT 1
              FROM skus
              JOIN products ON products.id = skus.product_id
             WHERE products.brand_id = brands.id
               AND skus.visible_b2b
        )
        """
    )


def downgrade() -> None:
    op.drop_column("skus", "b2b_markup_pct")
    op.drop_column("skus", "visible_b2b")
    op.drop_column("brands", "visible_b2b")
