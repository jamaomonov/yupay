"""SQLAlchemy ORM for the ``merchants`` module.

Five tables: the reseller account itself, its cabinet operator(s), the API
keys its server uses against ``/merchant/v1``, the one outgoing-webhook
endpoint it may register, and the outbox of deliveries to that endpoint. See
``docs/superpowers/specs/2026-09-06-merchant-b2b-design.md`` §6 and §10.

A merchant here is a *reseller of ours* — the opposite sense of "merchant"
from Click/Payme's own credentials (``merchant_id``), where **we** are the
merchant to the acquirer. See the module README for the terminology note in
full.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    Dialect,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from yupay.core.db import Base

#: Column bound on ``merchant_webhooks.url``. Generous for a path with a
#: token in it, short enough that the value stays loggable and renderable.
WEBHOOK_URL_MAX = 512

#: Column bound on ``merchant_webhook_deliveries.response_body`` — 2 KiB of
#: the merchant's own response, kept for diagnosis. It is attacker-influenced
#: text (their server writes it, and their server may be compromised) that
#: our cabinet renders from M4, so it is capped in the schema rather than
#: trusted to stay small: enough to hold a real error page's first useful
#: lines, far too little to be worth using as storage.
WEBHOOK_RESPONSE_BODY_MAX = 2048


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


class MerchantWebhook(Base):
    """The one endpoint we POST a merchant's events to (spec §10).

    **One row per merchant in v1** — ``merchant_id`` is unique, not merely
    indexed. Several endpoints per merchant is a different shape (a fan-out
    with per-endpoint failure state and per-endpoint secrets), not a nullable
    column bolted onto this one, so it waits for a version that wants it.

    ``secret_enc``/``secret_nonce`` hold the signing key **encrypted at rest**
    under ``core.crypto``'s :data:`~yupay.core.crypto.PURPOSE_MERCHANT_WEBHOOK`
    label — the same decision, for the same reason, as
    :class:`MerchantApiKey`: we compute the HMAC ourselves on every delivery,
    and a digest cannot key an HMAC (ADR-0069 §4). Its own purpose label
    keeps it independent of the machine-API key even though both derive from
    one ``INVENTORY_ENC_KEY``.

    Disabling is a timestamp, never a DELETE: ``merchant_webhook_deliveries``
    is the cabinet's log from M4 and must stay readable, and re-enabling a
    hook an operator (or the failure-streak auto-disable) switched off should
    not mean re-onboarding the merchant with a new secret.
    """

    __tablename__ = "merchant_webhooks"
    __table_args__ = (
        UniqueConstraint("merchant_id", name="uq_merchant_webhooks_merchant"),
        # Bare suffix — ``core.db.NAMING_CONVENTION`` prepends
        # ``ck_merchant_webhooks_`` itself, and would double a full name.
        CheckConstraint("failure_streak >= 0", name="streak_nonneg"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    #: Validated at save time against the same blocked ranges catalog image
    #: URLs get (``catalog.image_url_safety.validate_public_https_url``).
    #: That check reads notation, not resolved addresses — the connect-time
    #: check is the outbound client's job.
    url: Mapped[str] = mapped_column(String(WEBHOOK_URL_MAX), nullable=False)
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    secret_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    #: Set by an admin disable or by the failure-streak auto-disable. While
    #: it is non-NULL nothing is enqueued and nothing is delivered.
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Consecutive failed deliveries; reset to 0 by any success and by a
    #: fresh URL. The auto-disable threshold reads it.
    failure_streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class MerchantWebhookDelivery(Base):
    """One queued or attempted delivery — the outbox, and M4's delivery log.

    The ADR-0064 shape: a row with a claimable ``status``, inserted in the
    same transaction as the fact that causes it, drained by ``apps/worker``
    with ``FOR UPDATE SKIP LOCKED``. ``pending`` → ``in_progress`` →
    ``delivered`` | ``failed``, spelled here because Tasks 3 and 4 both
    depend on the exact words.

    It is deliberately also a **human-readable log**: a support engineer
    answering "did the merchant get told, and what did their server say?"
    reads one row — the event, the payload we sent, the code that came back,
    the first bytes of their body, and our own error text.

    ``event_type`` carries no CHECK constraint. The v1 vocabulary is exactly
    ``order.status_changed`` and ``balance.credited``, enforced at the
    enqueue boundary, so adding a third event stays a code change rather
    than a migration on a growing table.
    """

    __tablename__ = "merchant_webhook_deliveries"
    __table_args__ = (
        # Bare suffixes, as above: the convention supplies the
        # ``ck_merchant_webhook_deliveries_`` prefix.
        CheckConstraint("status IN ('pending','in_progress','delivered','failed')", name="status"),
        CheckConstraint("attempts_count >= 0", name="attempts_nonneg"),
        # The claim query: pending rows whose backoff has elapsed, oldest
        # first. Partial, so it stays the size of the backlog rather than of
        # the log — which is the table that grows.
        Index(
            "ix_merchant_webhook_deliveries_pending",
            "next_attempt_at",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
        # Two readers need this one: the ``ON DELETE CASCADE`` above (an
        # unindexed child FK turns deleting a merchant into a seq scan of
        # the whole log) and M4's per-merchant delivery list, newest first.
        Index(
            "ix_merchant_webhook_deliveries_merchant_id",
            "merchant_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    #: Exactly the JSON body we sign and POST. Money is a **string** in it —
    #: JSONB has no Decimal and a float would round a balance.
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    #: When the next attempt becomes due. NULL means "now" — the first
    #: attempt has no backoff to wait out.
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The first :data:`WEBHOOK_RESPONSE_BODY_MAX` characters of the
    #: merchant's response. Bounded in the **column**, not only by the
    #: writer: this is text a third-party server chose, it is rendered in
    #: our own cabinet from M4, and "the writer truncates" is a promise a
    #: future writer can forget. Callers truncate to the same constant so
    #: they never trip the bound.
    response_body: Mapped[str | None] = mapped_column(
        String(WEBHOOK_RESPONSE_BODY_MAX), nullable=True
    )
    #: Our own description of the failure — a typed refusal from the
    #: outbound client, or an exception summary. Ours, not theirs, which is
    #: why it is unbounded ``Text`` where ``response_body`` is not.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


__all__ = [
    "WEBHOOK_RESPONSE_BODY_MAX",
    "WEBHOOK_URL_MAX",
    "InetAsText",
    "Merchant",
    "MerchantApiKey",
    "MerchantUser",
    "MerchantWebhook",
    "MerchantWebhookDelivery",
]
