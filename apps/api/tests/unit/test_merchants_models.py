"""Pin the merchant schema's table/constraint names.

These names are load-bearing for the migration (0065) and for every later
module (auth, cabinet BFF, admin) that references them. A rename here is a
breaking change to all of those.
"""

from __future__ import annotations

from yupay.modules.merchants.models import Merchant, MerchantApiKey


def test_merchant_status_constraint_names_are_stable() -> None:
    """Pin table/constraint names the later migrations and admin depend on."""
    assert Merchant.__tablename__ == "merchants"
    names = {c.name for c in Merchant.__table__.constraints}  # type: ignore[attr-defined]
    assert "ck_merchants_status_known" in names


def test_api_key_key_id_is_unique() -> None:
    """The public key id is unique and the secret hash is a fixed-length hex digest."""
    cols = MerchantApiKey.__table__.columns
    assert cols["key_id"].unique
    assert cols["secret_hash"].type.length == 64  # type: ignore[attr-defined]
