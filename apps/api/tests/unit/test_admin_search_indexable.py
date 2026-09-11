"""The admin global search must be spelled the way its indexes are.

Migration 0039 built two indexes specifically for finding an order from the
support desk: `ix_orders_id_prefix` on `(id::text) text_pattern_ops`, and
`ix_orders_guest_email_trgm`, a trigram GIN on `lower(guest_email::text)`.

`pg_stat_user_indexes` on production showed `ix_orders_guest_email_trgm` with
`idx_scan = 0` — never used, not once. The reason is that this search used
`ILIKE`, which compiles to the `~~*` operator: it cannot use a
`text_pattern_ops` btree and does not match a `lower(...)` expression index. So
every support search sequentially scanned `orders`, holding one of the twenty
pool connections for the duration, and nobody suspected the index because the
index existed.

`orders/service.py::_admin_search_clause` already gets this right and carries a
comment explaining exactly this trap. These tests pin the same spelling here.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql
from yupay.modules.admin.service import (
    order_search_clause,
    payment_search_clause,
    user_search_clause,
)


def _sql(clause: object) -> str:
    """Compiled SQL, lowercased. `%%` is collapsed to `%`: literal binding
    doubles it for the driver, which is a compiler artefact rather than part of
    the predicate."""
    return (
        str(
            clause.compile(  # type: ignore[attr-defined]
                # SQLAlchemy ships no types for the dialect constructor.
                dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
                compile_kwargs={"literal_binds": True},
            )
        )
        .lower()
        .replace("%%", "%")
    )


@pytest.mark.parametrize(
    ("name", "clause"),
    [
        ("orders", order_search_clause("someone@example.com")),
        ("payments", payment_search_clause("abc123")),
        ("users", user_search_clause("someone@example.com", tg_id=None)),
    ],
)
def test_no_ilike_anywhere_in_the_search(name: str, clause: object) -> None:
    sql = _sql(clause)
    assert "ilike" not in sql, f"{name} still uses ILIKE, which no index here can serve"
    assert "~~*" not in sql, f"{name} compiles to the case-insensitive operator"


def test_an_email_fragment_matches_the_trigram_index_expression() -> None:
    """The index is on `lower(guest_email::text)`; a predicate of any other
    shape silently seq-scans."""
    sql = _sql(order_search_clause("Someone@Example.com"))
    assert "lower" in sql
    assert "someone@example.com" in sql, "the term itself must be lowercased, not just the column"


def test_an_id_fragment_is_a_prefix_match_on_the_cast() -> None:
    """`ix_orders_id_prefix` is on `(id::text) text_pattern_ops` and only serves
    an anchored prefix — a leading `%` would make it useless."""
    sql = _sql(order_search_clause("019f6b61"))
    assert "like '019f6b61%'" in sql, sql
    assert "like '%019f6b61" not in sql, "a leading wildcard cannot use the prefix index"


def test_short_terms_are_refused_before_they_reach_the_database() -> None:
    """A one- or two-character prefix matches a large slice of the table and is
    never what an operator meant."""
    assert order_search_clause("ab") is None
    assert payment_search_clause("x") is None
    assert user_search_clause("ab", tg_id=None) is None


# ---------- admin order list (`orders.admin_search`) ----------


def test_admin_order_list_search_refuses_short_terms() -> None:
    from yupay.modules.orders.admin_search import admin_search_clause

    assert admin_search_clause("ab") is None


def test_admin_order_list_search_has_no_ilike() -> None:
    from yupay.modules.orders.admin_search import admin_search_clause

    sql = _sql(admin_search_clause("pubg"))
    assert "ilike" not in sql
    assert "~~*" not in sql


def test_admin_order_list_search_keeps_the_id_prefix_indexable() -> None:
    from yupay.modules.orders.admin_search import admin_search_clause

    sql = _sql(admin_search_clause("019f6b61"))
    assert "like '019f6b61%'" in sql, sql


def test_admin_order_list_search_matches_catalog_user_and_merchant() -> None:
    from yupay.modules.orders.admin_search import admin_search_clause

    sql = _sql(admin_search_clause("pubg"))
    assert "product_translations" in sql
    assert "brand_translations" in sql
    assert "users" in sql
    assert "merchants" in sql
    assert "like '%pubg%'" in sql


def test_admin_order_list_email_search_hits_guest_and_user() -> None:
    from yupay.modules.orders.admin_search import admin_search_clause

    sql = _sql(admin_search_clause("Someone@Example.com"))
    assert "lower" in sql
    assert "someone@example.com" in sql
    assert "guest_email" in sql
    assert "users" in sql
