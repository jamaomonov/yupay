"""``orders.source`` has two provenances, and only one of them is client-declared.

Migration 0073 widened ``ck_orders_source_known`` to ``merchant_api`` and
``merchant_panel`` so a B2B order stops landing in ``unknown``. Widening the
column's vocabulary must **not** widen the header's: ``ORDER_SOURCES`` is what
a client may declare for itself via ``X-Yupay-Surface``, and a storefront
request that asked for ``merchant_api`` would dress a retail sale up as a
reseller's — on the one column an operator reads to tell them apart.

``source`` gates nothing either way (it is not an authorisation input), so
this is not a privilege boundary. It is the integrity of an operator's answer
to "where did this come from".
"""

from __future__ import annotations

import pytest
from yupay.modules.orders.service import (
    ORDER_SOURCES,
    SOURCE_MERCHANT_API,
    SOURCE_MERCHANT_PANEL,
    normalise_source,
)


@pytest.mark.parametrize("declared", ["web", "miniapp", "bot"])
def test_a_retail_surface_is_taken_at_its_word(declared: str) -> None:
    assert normalise_source(declared) == declared
    assert normalise_source(declared.upper()) == declared


@pytest.mark.parametrize("declared", [None, "", "  ", "'; DROP TABLE", "partners", "admin"])
def test_anything_unrecognised_records_as_unknown(declared: str | None) -> None:
    """An unreadable header must never be able to refuse a sale."""
    assert normalise_source(declared) == "unknown"


@pytest.mark.parametrize("declared", [SOURCE_MERCHANT_API, SOURCE_MERCHANT_PANEL])
def test_a_client_cannot_declare_itself_a_b2b_surface(declared: str) -> None:
    """Legal in the database, unsayable by a client.

    Both values are written server-side — ``merchant_api`` by
    ``merchants.orders.place`` after the request signature said which merchant
    is calling, ``merchant_panel`` by M4's cabinet when it ships. Accepting
    either from a header would make the column a claim again on exactly the
    rows where it is currently a fact.
    """
    assert declared not in ORDER_SOURCES
    assert normalise_source(declared) == "unknown"


def test_the_model_allows_every_value_the_migration_does() -> None:
    """The ORM's CHECK and migration 0073's must not drift apart.

    Nothing else would catch it: the integration suite builds its schema from
    the migrations, so a model-only edit is invisible there, and ``metadata``
    is what a future ``create_all`` or autogenerate diff would believe.
    """
    from sqlalchemy import CheckConstraint
    from yupay.modules.orders.models import Order

    # Selected by predicate, not by name: the metadata name is
    # ``ck_orders_ck_orders_source_known`` — the naming convention re-templates
    # an explicitly named CheckConstraint, and this one shipped that way (see
    # ``core.db.NAMING_CONVENTION``). Matching on the text is both stabler and
    # the thing actually under test.
    predicates = [
        str(c.sqltext)
        for c in Order.metadata.tables["orders"].constraints
        if isinstance(c, CheckConstraint) and str(c.sqltext).startswith("source IN")
    ]
    assert len(predicates) == 1, predicates
    for value in (*ORDER_SOURCES, "unknown", SOURCE_MERCHANT_API, SOURCE_MERCHANT_PANEL):
        assert f"'{value}'" in predicates[0], f"{value} is not in {predicates[0]}"
