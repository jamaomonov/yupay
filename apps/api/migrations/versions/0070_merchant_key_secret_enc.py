"""Machine credentials at rest: encrypt the secret instead of hashing it.

0065 gave ``merchant_api_keys`` a ``secret_hash`` (SHA-256 hex). That column
cannot support the signature scheme spec §9.2 requires: an HMAC cannot be
verified without the key material, so a one-way digest either forces the
digest itself to be the signing key — which is storing key material in the
clear under a hashed-sounding name — or forbids HMAC entirely.

So the secret is now **encrypted at rest** (XSalsa20-Poly1305 via
``core.crypto``, HKDF-derived per-purpose key), exactly as ``inventory_codes``
already protects voucher codes. The asymmetry is what settled it: a voucher
code is worth one SKU, a signing key is worth a merchant's whole deposit, and
protecting the smaller instrument and not the larger one is backwards.

- ``secret_enc``   — ciphertext with its Poly1305 tag.
- ``secret_nonce`` — the per-row 24-byte nonce.
- ``secret_hash``  — dropped.

**No backfill and no data risk: the table is empty everywhere.** M1 is not
deployed to production, and until this milestone nothing in the codebase ever
wrote a ``merchant_api_keys`` row — the issuance endpoint arrives in the same
change as this migration. Zero keys have been issued, so there is nothing to
re-encrypt and no integrator to break.

``NOT NULL`` on both new columns is therefore safe without a server default;
the downgrade recreates ``secret_hash`` the same way, and is likewise only
correct while the table is empty (it says so in place).

Revision ID: 0070_merchant_key_secret_enc
Revises: 0069_orders_merchant_idempotency
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0070_merchant_key_secret_enc"
down_revision: str | None = "0069_orders_merchant_idempotency"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("merchant_api_keys", sa.Column("secret_enc", sa.LargeBinary(), nullable=False))
    op.add_column("merchant_api_keys", sa.Column("secret_nonce", sa.LargeBinary(), nullable=False))
    op.drop_column("merchant_api_keys", "secret_hash")


def downgrade() -> None:
    # Only correct because the table is empty: there is no way to recover a
    # SHA-256 of a secret we can decrypt, and nothing to recover it for.
    op.add_column(
        "merchant_api_keys", sa.Column("secret_hash", sa.String(length=64), nullable=False)
    )
    op.drop_column("merchant_api_keys", "secret_nonce")
    op.drop_column("merchant_api_keys", "secret_enc")
