"""SQLAlchemy ORM for the ``merchants`` module.

Three tables: the reseller account itself, its cabinet operator(s), and the
API keys its server uses against ``/merchant/v1``. See
``docs/superpowers/specs/2026-09-06-merchant-b2b-design.md`` §6.

A merchant here is a *reseller of ours* — the opposite sense of "merchant"
from Click/Payme's own credentials (``merchant_id``), where **we** are the
merchant to the acquirer. See the module README for the terminology note in
full.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    Dialect,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from yupay.core.db import Base


class InetAsText(TypeDecorator[str]):
    """``INET`` in Postgres, plain ``str`` in Python.

    Mirrors ``evidence.models.InetAsText``: asyncpg hands back ``ipaddress``
    objects for ``INET`` columns while psycopg returns text, and pinning the
    Python side to ``str`` keeps every consumer from having to know which
    driver is underneath. Not imported from ``evidence`` directly — that
    module's type is private to its own concern (an unhashed IP kept for
    chargeback evidence), and this one's is a merchant's own allow-listed
    addresses.
    """

    impl = INET
    cache_ok = True

    def process_result_value(self, value: object, dialect: Dialect) -> str | None:  # noqa: ARG002
        return None if value is None else str(value)


class Merchant(Base):
    """A B2B reseller account.

    ``markup_adjustment_pp`` is dormant in v1 — every merchant prices off the
    flat per-SKU ``b2b_markup_pct`` (spec §8.1). The column exists now so a
    later per-merchant override (spec §8.3) is a data change, not a schema
    change.
    """

    __tablename__ = "merchants"
    # Note the bare suffix, not the full name: the metadata's naming
    # convention (``core.db.NAMING_CONVENTION``) prepends ``ck_merchants_``
    # itself, and CheckConstraint is the one constraint type where that
    # convention fires even when a name is already given — passing the full
    # name here would double it (``ck_merchants_ck_merchants_status_known``).
    __table_args__ = (CheckConstraint("status IN ('active', 'frozen')", name="status_known"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    #: Per-merchant markup adjustment in percentage points; NULL in v1, see
    #: spec §8.3.
    markup_adjustment_pp: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class MerchantUser(Base):
    """A cabinet operator for a merchant.

    One user per merchant in v1 — the FK already permits more, so adding
    seats later needs no migration. Separate table and separate auth from
    buyer ``users``, the same split ``affiliate_partners`` makes: a merchant
    operator is not a customer.
    """

    __tablename__ = "merchant_users"
    __table_args__ = (Index("ix_merchant_users_merchant_id", "merchant_id"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    email_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'Asia/Tashkent'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class MerchantApiKey(Base):
    """An API credential a merchant's server uses against ``/merchant/v1``.

    ``key_id`` is the public half (``ypm_``-prefixed, sent on every request);
    ``secret_enc``/``secret_nonce`` hold the private half, encrypted at rest
    and never returned after creation.
    """

    __tablename__ = "merchant_api_keys"
    __table_args__ = (Index("ix_merchant_api_keys_merchant_id", "merchant_id"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    key_id: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    #: The signing secret, encrypted at rest under ``core.crypto``'s
    #: ``PURPOSE_MERCHANT_API_KEY`` key (XSalsa20-Poly1305, per-row nonce) —
    #: the same protection ``inventory_codes`` gives voucher codes, which are
    #: worth strictly less. It is **encrypted, not hashed**, because an HMAC
    #: cannot be verified without the key material; see ``signing.py``.
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    secret_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("''"))
    #: NULL = filter off (no IP restriction).
    ip_allowlist: Mapped[list[str] | None] = mapped_column(ARRAY(InetAsText), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


__all__ = ["InetAsText", "Merchant", "MerchantApiKey", "MerchantUser"]
