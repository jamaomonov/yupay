"""Pin the merchant schema's table/constraint names.

These names are load-bearing for the migration (0065) and for every later
module (auth, cabinet BFF, admin) that references them. A rename here is a
breaking change to all of those.
"""

from __future__ import annotations

from sqlalchemy import LargeBinary
from yupay.modules.merchants.models import Merchant, MerchantApiKey


def test_merchant_status_constraint_names_are_stable() -> None:
    """Pin table/constraint names the later migrations and admin depend on."""
    assert Merchant.__tablename__ == "merchants"
    names = {c.name for c in Merchant.__table__.constraints}  # type: ignore[attr-defined]
    assert "ck_merchants_status_known" in names


def test_api_key_key_id_is_unique_and_the_secret_is_stored_encrypted() -> None:
    """The public key id is unique; the private half is ciphertext, not a digest.

    Rewritten in M2 (migration 0070): this pinned ``secret_hash`` being a
    64-char hex digest, which the signature scheme cannot use — an HMAC needs
    the key material back. The columns it pins now are the ones the auth path
    actually reads.
    """
    cols = MerchantApiKey.__table__.columns
    assert cols["key_id"].unique
    assert "secret_hash" not in cols
    assert isinstance(cols["secret_enc"].type, LargeBinary)
    assert isinstance(cols["secret_nonce"].type, LargeBinary)
    assert not cols["secret_enc"].nullable
    assert not cols["secret_nonce"].nullable
