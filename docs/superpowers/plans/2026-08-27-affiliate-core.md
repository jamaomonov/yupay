# Affiliate core: schema, ledger and commission accrual — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the affiliate program's data model, its five ledger account kinds, and the scheduled sweep that accrues and matures partner commission — with no user-visible surface.

**Architecture:** A new `affiliate` module in the FastAPI monolith owns six tables. Partner money lives in the existing double-entry ledger (`wallet`), split across three partner accounts so that "available to withdraw" is a ledger balance rather than a computation. Commission is posted by a scheduler sweep that finds delivered orders with an attribution and no commission row; `UNIQUE(order_id)` makes it idempotent by construction, so a missed or retried pass cannot double-pay and does not need reconciliation.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, APScheduler, pytest + testcontainers.

**Spec:** `docs/superpowers/specs/2026-08-27-affiliate-program-design.md`

**Plan 1 of 7.** The spec's build order lists seven independently shippable steps; this plan is step 1. Later plans cover the discount on the order path (step 2), the checkout promo field (3), partner auth and panel API (4), `apps/partners` (5), admin screens (6), infrastructure (7). Nothing in this plan is visible to a customer or a partner: it can go to production before any code has been issued.

## Global Constraints

Copied from `CLAUDE.md` and the spec. Every task's requirements implicitly include this section.

- Python 3.12, ruff `line-length = 100`, `target-version = "py312"`.
- `mypy --strict`. Every function annotated, private ones included. No `Any` without a justifying inline comment.
- Google-style docstrings on every public function, class and module.
- Async everywhere on the request path. No `requests`, no `time.sleep`, no sync DB calls.
- File length soft limit 400 LOC (Python); split before 500. Function soft limit 50 LOC; cyclomatic complexity ≤ 10.
- **All money is `Decimal` in the database, never float.**
- **This module moves money, so the coverage gate is 95%, not 80%** (`CLAUDE.md` §8).
- Never log PII. Order ids and amounts are fine to log; emails, phones and Telegram ids are not.
- **Alembic revision ids must be at most 32 characters** — `alembic_version.version_num`
  is `varchar(32)` and a longer id fails at the very end of `upgrade`, after the
  migration body has already run.
- Conventional Commits, scope `api/affiliate` or `scheduler/affiliate`.
- Commit after every green test run. Do not push — this repository's rule is that pushing and deploying happen only on explicit instruction.
- Parameters from the spec, all as settings with these defaults: hold period **14 days**, sweep interval **5 minutes**, commission percent range **1–2%**, discount percent range **3–10%**, minimum payout **50 000 UZS**, code format **4–32 chars of `A-Z0-9-`, stored uppercase**.

## File Structure

**Created:**

| File                                                           | Responsibility                                                                                        |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `apps/api/src/yupay/modules/affiliate/__init__.py`             | Package marker.                                                                                       |
| `apps/api/src/yupay/modules/affiliate/models.py`               | The six ORM models. Nothing else.                                                                     |
| `apps/api/src/yupay/modules/affiliate/ledger.py`               | Account-kind constants and the three posting helpers. The only file that calls `wallet.service.post`. |
| `apps/api/src/yupay/modules/affiliate/accrual.py`              | `accrue_commissions`, `mature_commissions`, `void_commission`. Pure service logic, no HTTP.           |
| `apps/api/src/yupay/modules/affiliate/api.py`                  | The module's public facade — what other modules and the scheduler import.                             |
| `apps/api/src/yupay/modules/affiliate/README.md`               | Module documentation, required by `CLAUDE.md` §5.                                                     |
| `apps/api/migrations/versions/0057_affiliate_program.py`       | The six tables.                                                                                       |
| `apps/scheduler/src/yupay_scheduler/jobs/affiliate_accrual.py` | The periodic job wrapper.                                                                             |
| `apps/api/tests/integration/test_affiliate_accrual.py`         | Integration tests against a real Postgres.                                                            |
| `docs/decisions/0061-affiliate-commission-by-sweep.md`         | ADR for accrual-by-sweep.                                                                             |

**Modified:**

| File                                           | Change                                    |
| ---------------------------------------------- | ----------------------------------------- |
| `apps/api/src/yupay/modules/wallet/service.py` | Five entries added to `NORMAL_SIDE`.      |
| `apps/api/src/yupay/core/config.py`            | Four affiliate settings.                  |
| `apps/scheduler/src/yupay_scheduler/main.py`   | Import and register the new job.          |
| `docs/architecture/module-map.md`              | Add the `affiliate` module and its edges. |

`ledger.py` and `accrual.py` are separate on purpose: postings are the part a reviewer must read most carefully, and keeping them out of the query logic means that file stays short enough to hold in your head at once.

---

### Task 1: Ledger account kinds

The `wallet` module refuses to create an account whose `kind` is not in `NORMAL_SIDE`, so nothing else in this plan can post until these exist. This is a change to shared money code and is worth reviewing on its own.

**Files:**

- Modify: `apps/api/src/yupay/modules/wallet/service.py:24-41` (the `NORMAL_SIDE` dict)
- Modify: `apps/api/src/yupay/modules/wallet/schemas.py:13-32` (the `AccountKind` and `OwnerType` literals)
- Create: `apps/api/migrations/versions/0056_wallet_partner_accounts.py`
- Test: `apps/api/tests/integration/test_affiliate_accrual.py`

**Interfaces:**

- Consumes: nothing.
- Produces: the string constants `"partner_pending"`, `"partner_balance"`, `"partner_payout_hold"`, `"house_affiliate_expense"`, `"house_affiliate_paid"`, all accepted by `wallet.service.ensure_account(db, owner_type=..., owner_id=..., kind=..., currency=...)` and all nameable as `wallet.schemas.AccountKind`. Also `"partner"` as a `wallet.schemas.OwnerType`.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/integration/test_affiliate_accrual.py`:

```python
"""Affiliate commission: ledger accounts, accrual, maturation, voiding.

The sweep is idempotent by construction — ``UNIQUE(order_id)`` on
``affiliate_commissions`` — so these tests lean on running it twice rather than
on mocking a scheduler.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.wallet import service as wallet_service

pytestmark = pytest.mark.asyncio

AFFILIATE_KINDS = [
    "partner_pending",
    "partner_balance",
    "partner_payout_hold",
    "house_affiliate_expense",
    "house_affiliate_paid",
]


@pytest.mark.parametrize("kind", AFFILIATE_KINDS)
async def test_affiliate_account_kinds_are_postable(db_session: AsyncSession, kind: str) -> None:
    """Every affiliate account kind can be created through the wallet facade."""
    owner_type = "house" if kind.startswith("house_") else "partner"
    account = await wallet_service.ensure_account(
        db_session,
        owner_type=owner_type,
        owner_id="house" if owner_type == "house" else "00000000-0000-0000-0000-000000000001",
        kind=kind,
        currency="UZS",
    )
    assert account.kind == kind
    assert await wallet_service.balance(db_session, account.id) == Decimal("0")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_accrual.py -v`
Expected: FAIL — five parametrized cases raise `ValidationError: unknown account kind: partner_pending` (and so on).

- [ ] **Step 3: Add the kinds**

In `apps/api/src/yupay/modules/wallet/service.py`, extend the `NORMAL_SIDE` dict. Insert after the `"house_payments_received": "D",` entry and before `"house_revenue": "C",`:

```python
    # Affiliate program (see docs/superpowers/specs/2026-08-27-affiliate-program-design.md).
    # Partner money is split across three accounts so that "available to
    # withdraw" is a ledger balance rather than a sum computed over the
    # commissions table — one source of truth, and a payout request that
    # reserves its money cannot be raced into an overdraft.
    #
    # `partner_pending`     commission accrued, still inside the hold period
    # `partner_balance`     matured, withdrawable
    # `partner_payout_hold` reserved by an open payout request
    #
    # The house side mirrors the promo pair: `house_affiliate_expense` is
    # credited when commission is earned, `house_affiliate_paid` is debited
    # when it actually leaves for a partner's card. Two accounts, because
    # "what we owe partners" and "what we have paid partners" answer
    # different questions.
    "partner_pending": "D",
    "partner_balance": "D",
    "partner_payout_hold": "D",
    "house_affiliate_expense": "D",
    "house_affiliate_paid": "D",
```

- [ ] **Step 4: Extend the module's type vocabulary**

`NORMAL_SIDE` is what `ensure_account` validates against, but it is not the
whole story: `apps/api/src/yupay/modules/wallet/schemas.py` declares the
literal types the module publishes, and they are a closed set.

In `schemas.py`, add the five kinds to `AccountKind` (line 13) and `"partner"`
to `OwnerType` (line 26):

```python
AccountKind = Literal[
    "user_wallet",
    "user_cashback",
    "user_promo_credit",
    "house_revenue",
    "house_cogs",
    "house_promo_expense",
    "house_payments_received",
    "house_refunds",
    "house_fx_pnl",
    "provider_clearing",
    "partner_pending",
    "partner_balance",
    "partner_payout_hold",
    "house_affiliate_expense",
    "house_affiliate_paid",
]

OwnerType = Literal["user", "house", "provider", "partner"]
```

**Leave `USER_VISIBLE_KINDS` exactly as it is.** It is the allow-list for what a
customer sees in their own wallet, and partner money must never appear there.
Adding to it would be a data leak, not a convenience.

Nothing breaks today without this — `ensure_account` takes plain `str`, and the
one admin route that serialises accounts (`admin_user_ledger`) is scoped to a
single user, so a `partner` account cannot reach it. It matters because these
literals are the vocabulary the partner panel will be typed against in plan 4,
and because a module whose declared kinds disagree with the kinds it accepts is
a trap for the next reader.

- [ ] **Step 5: Widen the CHECK constraints**

`NORMAL_SIDE` and `AccountKind` are not the last word. `wallet_accounts` carries
two CHECK constraints enumerating the allowed values, created in
`0009_wallet_init.py` and last widened by `0018_house_payments_received.py`.
They are what actually stops the INSERT, and they fail with a constraint name
and nothing else.

Create `apps/api/migrations/versions/0056_wallet_partner_accounts.py`, following
the drop-and-recreate shape of 0018 (no backfill is needed — nothing has ever
written these kinds):

- `ck_wallet_accounts_owner_type`: add `"partner"` to `("user", "house", "provider")`.
- `ck_wallet_accounts_kind`: add the five new kinds to the existing ten.
- `downgrade` deletes partner postings and accounts before narrowing the CHECKs
  back, or the constraint cannot be recreated.

Read `0018_house_payments_received.py` first — it is the precedent and its
`_OLD_KINDS` / `_NEW_KINDS` pattern is what to copy.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_accrual.py -v`
Expected: PASS, 5 passed.

- [ ] **Step 7: Typecheck and lint**

Run: `cd apps/api && uv run mypy src && uv run ruff check src tests && uv run ruff format --check src tests`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/yupay/modules/wallet/service.py apps/api/src/yupay/modules/wallet/schemas.py apps/api/migrations/versions/0056_wallet_partner_accounts.py apps/api/tests/integration/test_affiliate_accrual.py
git commit -m "feat(api/affiliate): five ledger account kinds for partner money

Partner money splits across pending / balance / payout_hold so that
'available to withdraw' is a ledger balance, not a sum over the commissions
table. A payout request reserves its money, so two requests cannot overdraw."
```

---

### Task 2: Models and migration

**Files:**

- Create: `apps/api/src/yupay/modules/affiliate/__init__.py`
- Create: `apps/api/src/yupay/modules/affiliate/models.py`
- Create: `apps/api/migrations/versions/0057_affiliate_program.py`
- Test: `apps/api/tests/integration/test_affiliate_accrual.py`

**Interfaces:**

- Consumes: nothing from earlier tasks.
- Produces: `AffiliatePartner`, `AffiliateCode`, `AffiliateAttribution`, `AffiliateCommission`, `AffiliatePayout`, `AffiliateSession` — importable from `yupay.modules.affiliate.models`. Column names are used verbatim by every later task and by plans 2–6.

- [ ] **Step 1: Write the failing test**

Append to `apps/api/tests/integration/test_affiliate_accrual.py`:

```python
async def test_attribution_is_unique_per_user(db_session: AsyncSession) -> None:
    """A buyer belongs to exactly one partner, enforced by the database."""
    from sqlalchemy.exc import IntegrityError
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.models import (
        AffiliateAttribution,
        AffiliateCode,
        AffiliatePartner,
    )
    from yupay.modules.users.models import User

    user = User(id=new_id())
    partner_a = AffiliatePartner(id=new_id(), email=f"a-{new_id()}@example.test", status="active")
    partner_b = AffiliatePartner(id=new_id(), email=f"b-{new_id()}@example.test", status="active")
    db_session.add_all([user, partner_a, partner_b])
    await db_session.flush()

    code_a = AffiliateCode(
        id=new_id(),
        partner_id=partner_a.id,
        code=f"A{new_id().replace('-', '')[:10].upper()}",
        discount_percent=Decimal("5"),
        commission_percent=Decimal("2"),
    )
    code_b = AffiliateCode(
        id=new_id(),
        partner_id=partner_b.id,
        code=f"B{new_id().replace('-', '')[:10].upper()}",
        discount_percent=Decimal("5"),
        commission_percent=Decimal("2"),
    )
    db_session.add_all([code_a, code_b])
    await db_session.flush()

    db_session.add(
        AffiliateAttribution(
            id=new_id(), user_id=user.id, partner_id=partner_a.id, code_id=code_a.id
        )
    )
    await db_session.flush()

    db_session.add(
        AffiliateAttribution(
            id=new_id(), user_id=user.id, partner_id=partner_b.id, code_id=code_b.id
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_accrual.py::test_attribution_is_unique_per_user -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yupay.modules.affiliate'`.

- [ ] **Step 3: Create the package marker**

Create `apps/api/src/yupay/modules/affiliate/__init__.py`:

```python
"""Affiliate program: partners, codes, attribution, commission, payouts."""
```

- [ ] **Step 4: Write the models**

Create `apps/api/src/yupay/modules/affiliate/models.py`:

```python
"""SQLAlchemy ORM for the ``affiliate`` module.

Six tables. Two of the constraints here carry the design rather than merely
describing it:

``UNIQUE(user_id)`` on :class:`AffiliateAttribution` is what makes a buyer
belong to exactly one partner forever — the guarantee lives in the database,
not in a service that remembers to check.

``UNIQUE(order_id)`` on :class:`AffiliateCommission` is the whole of the
accrual sweep's idempotency. Two overlapping ticks cannot pay twice, and a
retried pass is free.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from yupay.core.db import Base


class AffiliatePartner(Base):
    """A partner, and their application.

    Application and account are one row, not two: the landing form inserts
    ``status='pending'`` and an admin moves it to ``active``. Nothing is copied
    on approval, and there is no state where an application is approved but the
    account does not yet exist.

    ``password_hash`` stays empty until the partner follows the set-password
    link, so an approved-but-not-yet-activated partner is simply one that
    cannot log in.

    ``user_id`` is the optional link to a buyer account. It exists for exactly
    one rule — a partner may not redeem their own code.
    """

    __tablename__ = "affiliate_partners"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'suspended', 'rejected')",
            name="ck_affiliate_partners_status",
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    admin_note: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AffiliateCode(Base):
    """A promo code owned by a partner.

    The percentages live on the code rather than the partner so one partner can
    run several codes on different channels with different terms at no extra
    cost. ``commission_percent`` is read live at accrual time, so raising a
    code's rate raises it for that code's future orders — the intuitive
    behaviour, and simpler than freezing a rate per referred buyer.

    Bounds are enforced in the database because they are the guard rail on our
    own margin: the spec measures break-even on the thinnest SKU at about a
    12.2% discount.
    """

    __tablename__ = "affiliate_codes"
    __table_args__ = (
        CheckConstraint(
            "discount_percent >= 3 AND discount_percent <= 10",
            name="ck_affiliate_codes_discount_range",
        ),
        CheckConstraint(
            "commission_percent >= 1 AND commission_percent <= 2",
            name="ck_affiliate_codes_commission_range",
        ),
        CheckConstraint("code = upper(code)", name="ck_affiliate_codes_upper"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    partner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("affiliate_partners.id", ondelete="RESTRICT"), nullable=False
    )
    #: Stored uppercase; lookups normalise the buyer's input the same way.
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    commission_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class AffiliateAttribution(Base):
    """A buyer permanently bound to the partner who introduced them.

    ``UNIQUE(user_id)`` is the guarantee, not a convention. It also makes the
    write race-safe without a lock: the row is created in the transaction that
    marks the first order paid, and a loser simply hits the constraint.
    """

    __tablename__ = "affiliate_attributions"
    __table_args__ = (UniqueConstraint("user_id", name="uq_affiliate_attributions_user"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    partner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("affiliate_partners.id", ondelete="RESTRICT"), nullable=False
    )
    code_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("affiliate_codes.id", ondelete="RESTRICT"), nullable=False
    )
    #: The order that created the binding. Nullable only so a future admin
    #: tool can bind a buyer by hand without inventing an order.
    first_order_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class AffiliateCommission(Base):
    """Commission earned on one delivered order.

    ``UNIQUE(order_id)`` is the accrual sweep's idempotency. ``percent`` and
    ``base_amount`` are frozen here at accrual time so that later edits to the
    code cannot revalue money already earned.
    """

    __tablename__ = "affiliate_commissions"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_affiliate_commissions_order"),
        CheckConstraint(
            "status IN ('pending', 'available', 'paid', 'void')",
            name="ck_affiliate_commissions_status",
        ),
        CheckConstraint("amount >= 0", name="ck_affiliate_commissions_amount_non_negative"),
        # The maturation sweep's only query.
        Index("ix_affiliate_commissions_status_available", "status", "available_at"),
        Index("ix_affiliate_commissions_partner_created", "partner_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    partner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("affiliate_partners.id", ondelete="RESTRICT"), nullable=False
    )
    code_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("affiliate_codes.id", ondelete="RESTRICT"), nullable=False
    )
    base_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class AffiliatePayout(Base):
    """A partner's withdrawal request.

    Card details are stored because the transfer is made by hand; they are PII
    and must never reach a log line.
    """

    __tablename__ = "affiliate_payouts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'approved', 'rejected', 'paid')",
            name="ck_affiliate_payouts_status",
        ),
        CheckConstraint("amount > 0", name="ck_affiliate_payouts_amount_positive"),
        Index("ix_affiliate_payouts_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    partner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("affiliate_partners.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    card_number: Mapped[str] = mapped_column(String(32), nullable=False)
    card_holder: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'requested'")
    )
    admin_note: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AffiliateSession(Base):
    """A partner's refresh session, mirroring ``auth``'s rotation policy."""

    __tablename__ = "affiliate_sessions"
    __table_args__ = (Index("ix_affiliate_sessions_partner", "partner_id"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    partner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("affiliate_partners.id", ondelete="CASCADE"), nullable=False
    )
    #: SHA-256 of the refresh token. The token itself is never stored.
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


__all__ = [
    "AffiliateAttribution",
    "AffiliateCode",
    "AffiliateCommission",
    "AffiliatePartner",
    "AffiliatePayout",
    "AffiliateSession",
]
```

- [ ] **Step 5: Write the migration**

Create `apps/api/migrations/versions/0057_affiliate_program.py`:

```python
"""Affiliate program: partners, codes, attribution, commission, payouts, sessions.

Six tables, no changes to existing ones — the order-side columns land in the
migration that carries the discount itself, so this one can ship on its own.

Two constraints do design work rather than validation. ``uq_affiliate_
attributions_user`` makes "a buyer belongs to one partner, forever" a database
guarantee. ``uq_affiliate_commissions_order`` is the entire idempotency story
of the accrual sweep: overlapping ticks cannot pay twice.

The percent ranges are CHECKed because they guard our own margin. Production
margin on price is 14.0% at worst; break-even on that SKU including commission
is a discount of about 12.2%, so a code outside 3-10% is a data-entry mistake
that costs money, not a preference.

Revision ID: 0057_affiliate_program
Revises: 0056_wallet_partner_accounts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057_affiliate_program"
down_revision: str | None = "0056_wallet_partner_accounts"
branch_labels: str | None = None
depends_on: str | None = None

_TS = sa.DateTime(timezone=True)
_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "affiliate_partners",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("email", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("contact", sa.String(length=128), nullable=True),
        sa.Column("channel", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("password_hash", sa.String(length=256), nullable=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("admin_note", sa.String(length=1024), nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("approved_at", _TS, nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'suspended', 'rejected')",
            name="ck_affiliate_partners_status",
        ),
    )

    op.create_table(
        "affiliate_codes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "partner_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("affiliate_partners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("commission_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.CheckConstraint(
            "discount_percent >= 3 AND discount_percent <= 10",
            name="ck_affiliate_codes_discount_range",
        ),
        sa.CheckConstraint(
            "commission_percent >= 1 AND commission_percent <= 2",
            name="ck_affiliate_codes_commission_range",
        ),
        sa.CheckConstraint("code = upper(code)", name="ck_affiliate_codes_upper"),
    )

    op.create_table(
        "affiliate_attributions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "partner_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("affiliate_partners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "code_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("affiliate_codes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "first_order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.UniqueConstraint("user_id", name="uq_affiliate_attributions_user"),
    )

    op.create_table(
        "affiliate_commissions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "partner_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("affiliate_partners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "code_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("affiliate_codes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("base_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("available_at", _TS, nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.UniqueConstraint("order_id", name="uq_affiliate_commissions_order"),
        sa.CheckConstraint(
            "status IN ('pending', 'available', 'paid', 'void')",
            name="ck_affiliate_commissions_status",
        ),
        sa.CheckConstraint("amount >= 0", name="ck_affiliate_commissions_amount_non_negative"),
    )
    op.create_index(
        "ix_affiliate_commissions_status_available",
        "affiliate_commissions",
        ["status", "available_at"],
    )
    op.create_index(
        "ix_affiliate_commissions_partner_created",
        "affiliate_commissions",
        ["partner_id", "created_at"],
    )

    op.create_table(
        "affiliate_payouts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "partner_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("affiliate_partners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("card_number", sa.String(length=32), nullable=False),
        sa.Column("card_holder", sa.String(length=128), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default=sa.text("'requested'")
        ),
        sa.Column("admin_note", sa.String(length=1024), nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("processed_at", _TS, nullable=True),
        sa.CheckConstraint(
            "status IN ('requested', 'approved', 'rejected', 'paid')",
            name="ck_affiliate_payouts_status",
        ),
        sa.CheckConstraint("amount > 0", name="ck_affiliate_payouts_amount_positive"),
    )
    op.create_index(
        "ix_affiliate_payouts_status_created", "affiliate_payouts", ["status", "created_at"]
    )

    op.create_table(
        "affiliate_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "partner_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("affiliate_partners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False, unique=True),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("revoked_at", _TS, nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
    )
    op.create_index("ix_affiliate_sessions_partner", "affiliate_sessions", ["partner_id"])


def downgrade() -> None:
    op.drop_table("affiliate_sessions")
    op.drop_table("affiliate_payouts")
    op.drop_table("affiliate_commissions")
    op.drop_table("affiliate_attributions")
    op.drop_table("affiliate_codes")
    op.drop_table("affiliate_partners")
```

- [ ] **Step 6: Make sure the models are imported so `Base.metadata` sees them**

Check how existing modules register their models with Alembic's autogenerate target:

Run: `cd apps/api && grep -rn "modules.promo.models\|import models" migrations/env.py src/yupay/core/db.py | head`

If there is a central import list (a `models` aggregator or an import block in `migrations/env.py`), add `from yupay.modules.affiliate import models as affiliate_models  # noqa: F401` alongside the others. If modules are discovered some other way, follow that mechanism instead. Do not skip this step — a model that `Base.metadata` never sees will pass tests against a hand-written migration and then drift silently.

- [ ] **Step 7: Run the migration and the test**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_accrual.py -v`
Expected: PASS, 6 passed. The `_apply_migrations` fixture runs `alembic upgrade head` against the testcontainer, so a broken migration fails here.

- [ ] **Step 8: Verify the downgrade works**

Run: `cd apps/api && uv run alembic downgrade 0055_admin_list_sort_indexes && uv run alembic upgrade head`
Expected: both succeed. Requires a local Postgres on `DATABASE_URL`; if none is running, start the dev stack with `make dev` first.

- [ ] **Step 9: Typecheck, lint, commit**

```bash
cd apps/api && uv run mypy src && uv run ruff check src tests && uv run ruff format --check src tests
cd ../.. && git add apps/api/src/yupay/modules/affiliate apps/api/migrations/versions/0057_affiliate_program.py apps/api/tests/integration/test_affiliate_accrual.py
git commit -m "feat(api/affiliate): schema for partners, codes, attribution and commission

UNIQUE(user_id) on attributions makes 'one buyer, one partner, forever' a
database guarantee. UNIQUE(order_id) on commissions is the accrual sweep's
whole idempotency story. Percent ranges are CHECKed because they guard our
margin: break-even on the thinnest SKU is a ~12.2% discount."
```

---

### Task 3: Accrue commission

**Files:**

- Create: `apps/api/src/yupay/modules/affiliate/ledger.py`
- Create: `apps/api/src/yupay/modules/affiliate/accrual.py`
- Modify: `apps/api/src/yupay/core/config.py`
- Test: `apps/api/tests/integration/test_affiliate_accrual.py`

**Interfaces:**

- Consumes: the models from Task 2; the account kinds from Task 1.
- Produces:
  - `affiliate.ledger.commission_amount(total: Decimal, percent: Decimal, currency: str) -> Decimal`
  - `affiliate.ledger.post_accrual(db, *, commission_id: str, partner_id: str, amount: Decimal, currency: str, order_id: str) -> None`
  - `affiliate.accrual.accrue_commissions(db: AsyncSession, *, hold_days: int, limit: int = 500) -> int`

- [ ] **Step 1: Add the settings**

In `apps/api/src/yupay/core/config.py`, add to the `Settings` class alongside the other integer settings:

```python
    # Affiliate program. See
    # docs/superpowers/specs/2026-08-27-affiliate-program-design.md.
    #: Days between an order being delivered and its commission becoming
    #: withdrawable. Covers the acquirers' dispute window without making a
    #: partner wait a month for a first payout.
    affiliate_hold_days: int = Field(default=14)
    #: How often the accrual sweep runs. Freshness costs nothing here — the
    #: hold period dominates — but the panel should never look stalled.
    affiliate_sweep_minutes: int = Field(default=5)
    #: Rows processed per sweep pass, per step. A backlog drains over several
    #: passes rather than in one long transaction.
    affiliate_sweep_batch: int = Field(default=500)
    #: Smallest withdrawal, in minor units of the partner's currency. Each
    #: payout is a manual bank transfer, so there is a floor. Estimated, not
    #: measured — revisit once real partner volumes exist.
    affiliate_min_payout: Decimal = Field(default=Decimal("50000"))
```

If `Decimal` is not already imported in that file, add `from decimal import Decimal` to its imports.

- [ ] **Step 2: Write the failing test**

Append to `apps/api/tests/integration/test_affiliate_accrual.py`. Put the helper at module level, below `AFFILIATE_KINDS`:

```python
async def _seed_delivered_order(
    db: AsyncSession,
    *,
    total_charged: Decimal,
    commission_percent: Decimal = Decimal("2"),
    currency: str = "UZS",
    delivered: bool = True,
    purpose: str = "catalog",
    with_attribution: bool = True,
) -> tuple[str, str, str]:
    """Create partner + code + user + (optionally) attribution + one order.

    Returns:
        ``(order_id, partner_id, user_id)``.
    """
    from datetime import timedelta

    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.models import (
        AffiliateAttribution,
        AffiliateCode,
        AffiliatePartner,
    )
    from yupay.modules.orders.models import Order
    from yupay.modules.users.models import User

    partner = AffiliatePartner(id=new_id(), email=f"p-{new_id()}@example.test", status="active")
    user = User(id=new_id())
    db.add_all([partner, user])
    await db.flush()

    code = AffiliateCode(
        id=new_id(),
        partner_id=partner.id,
        code=f"C{new_id().replace('-', '')[:10].upper()}",
        discount_percent=Decimal("5"),
        commission_percent=commission_percent,
    )
    db.add(code)
    await db.flush()

    moment = now()
    order = Order(
        id=new_id(),
        user_id=user.id,
        status="delivered" if delivered else "paid",
        currency=currency,
        total_usd=Decimal("1"),
        total_charged=total_charged,
        purpose=purpose,
        expires_at=moment + timedelta(days=1),
        delivered_at=moment if delivered else None,
    )
    db.add(order)
    await db.flush()

    if with_attribution:
        db.add(
            AffiliateAttribution(
                id=new_id(),
                user_id=user.id,
                partner_id=partner.id,
                code_id=code.id,
                first_order_id=order.id,
            )
        )
        await db.flush()

    return order.id, partner.id, user.id


async def test_accrual_posts_commission_to_pending(db_session: AsyncSession) -> None:
    """A delivered, attributed order accrues 2% into the partner's pending account."""
    from sqlalchemy import select
    from yupay.modules.affiliate.accrual import accrue_commissions
    from yupay.modules.affiliate.models import AffiliateCommission

    order_id, partner_id, _ = await _seed_delivered_order(
        db_session, total_charged=Decimal("100000")
    )

    accrued = await accrue_commissions(db_session, hold_days=14)
    assert accrued == 1

    row = (
        await db_session.execute(
            select(AffiliateCommission).where(AffiliateCommission.order_id == order_id)
        )
    ).scalar_one()
    assert row.amount == Decimal("2000")
    assert row.status == "pending"
    assert row.currency == "UZS"

    pending = await wallet_service.ensure_account(
        db_session,
        owner_type="partner",
        owner_id=partner_id,
        kind="partner_pending",
        currency="UZS",
    )
    assert await wallet_service.balance(db_session, pending.id) == Decimal("2000")


async def test_accrual_is_idempotent(db_session: AsyncSession) -> None:
    """Running the sweep twice pays once. This is the property the whole
    accrue-by-sweep design rests on."""
    _, partner_id, _ = await _seed_delivered_order(db_session, total_charged=Decimal("100000"))

    from yupay.modules.affiliate.accrual import accrue_commissions

    assert await accrue_commissions(db_session, hold_days=14) == 1
    assert await accrue_commissions(db_session, hold_days=14) == 0

    pending = await wallet_service.ensure_account(
        db_session,
        owner_type="partner",
        owner_id=partner_id,
        kind="partner_pending",
        currency="UZS",
    )
    assert await wallet_service.balance(db_session, pending.id) == Decimal("2000")


async def test_accrual_skips_undelivered_unattributed_and_topups(
    db_session: AsyncSession,
) -> None:
    """Three orders that must not earn commission."""
    from yupay.modules.affiliate.accrual import accrue_commissions

    await _seed_delivered_order(db_session, total_charged=Decimal("100000"), delivered=False)
    await _seed_delivered_order(
        db_session, total_charged=Decimal("100000"), with_attribution=False
    )
    await _seed_delivered_order(
        db_session, total_charged=Decimal("100000"), purpose="wallet_topup"
    )

    assert await accrue_commissions(db_session, hold_days=14) == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_accrual.py -v -k accrual`
Expected: FAIL with `ModuleNotFoundError: No module named 'yupay.modules.affiliate.accrual'`.

- [ ] **Step 4: Write the ledger helpers**

Create `apps/api/src/yupay/modules/affiliate/ledger.py`:

```python
"""Every ledger posting the affiliate program makes, and nothing else.

Kept apart from the query logic in ``accrual`` on purpose: these five lines of
bookkeeping are the part a reviewer must read most carefully, and a short file
is one you can hold in your head at once.

The postings mirror the shape ``promo.redeem`` already uses
(``D user_wallet / C house_promo_expense``), so no new rules enter double-entry
bookkeeping here.

Idempotency keys are derived from the row id rather than random, so a retry
after a timeout replays the original posting instead of making a second one —
``wallet.service.post`` returns the existing transaction for a key it has seen.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.wallet import service as wallet_service

#: Smallest payable unit per currency. UZS has no subunit in practice — Payme
#: and Click both reject fractions — so commission is whole sums.
_QUANTUM: dict[str, Decimal] = {"UZS": Decimal("1")}
_DEFAULT_QUANTUM = Decimal("0.01")

_HOUSE_OWNER = "house"


def commission_amount(total: Decimal, percent: Decimal, currency: str) -> Decimal:
    """Commission on ``total`` at ``percent``, rounded to a payable amount.

    Args:
        total: The order total the buyer actually paid, after any discount.
        percent: The code's commission percentage, e.g. ``Decimal("2")``.
        currency: ISO-4217 code, used to pick the rounding quantum.

    Returns:
        The commission, quantized to the currency's smallest payable unit.
    """
    quantum = _QUANTUM.get(currency.upper(), _DEFAULT_QUANTUM)
    return (total * percent / Decimal(100)).quantize(quantum, rounding=ROUND_HALF_UP)


async def _partner_account(
    db: AsyncSession, *, partner_id: str, kind: str, currency: str
) -> str:
    account = await wallet_service.ensure_account(
        db, owner_type="partner", owner_id=partner_id, kind=kind, currency=currency
    )
    return account.id


async def _house_account(db: AsyncSession, *, kind: str, currency: str) -> str:
    account = await wallet_service.ensure_account(
        db, owner_type=_HOUSE_OWNER, owner_id=_HOUSE_OWNER, kind=kind, currency=currency
    )
    return account.id


async def post_accrual(
    db: AsyncSession,
    *,
    commission_id: str,
    partner_id: str,
    amount: Decimal,
    currency: str,
    order_id: str,
) -> None:
    """Book earned commission: ``D partner_pending / C house_affiliate_expense``."""
    pending = await _partner_account(
        db, partner_id=partner_id, kind="partner_pending", currency=currency
    )
    expense = await _house_account(db, kind="house_affiliate_expense", currency=currency)
    await wallet_service.post(
        db,
        kind="affiliate.accrue",
        legs=[
            wallet_service.Leg(account_id=pending, direction="D", amount=amount, currency=currency),
            wallet_service.Leg(account_id=expense, direction="C", amount=amount, currency=currency),
        ],
        idempotency_key=f"affiliate.accrue:{commission_id}",
        reference=wallet_service.Reference(type="order", id=order_id),
        actor="scheduler",
    )


__all__ = ["commission_amount", "post_accrual"]
```

- [ ] **Step 5: Write the accrual sweep**

Create `apps/api/src/yupay/modules/affiliate/accrual.py`:

```python
"""The commission sweep: find work, post it, record it.

Deliberately not called from the fulfilment path. That path is already the
slowest in the system and is where a customer waits for a code; adding money
work to it buys a minute of freshness in a panel that sits behind a two-week
hold period anyway.

The design's safety property is that this function can be run at any time, any
number of times, concurrently with itself, and never pay twice — ``UNIQUE
(order_id)`` on ``affiliate_commissions`` decides the winner, and the ledger
posting is keyed off the commission row's own id. An order missed for any
reason is picked up by the next pass, so there is nothing to reconcile by hand.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.ids import new_id
from yupay.core.logging import get_logger
from yupay.modules.affiliate.ledger import commission_amount, post_accrual
from yupay.modules.affiliate.models import (
    AffiliateAttribution,
    AffiliateCode,
    AffiliateCommission,
)
from yupay.modules.orders.models import Order

log = get_logger("yupay.affiliate.accrual")


async def accrue_commissions(db: AsyncSession, *, hold_days: int, limit: int = 500) -> int:
    """Accrue commission for delivered, attributed orders that have none yet.

    Args:
        db: Session. The caller owns the transaction.
        hold_days: Days from now until the commission becomes withdrawable.
        limit: Maximum orders handled in one pass, so a backlog drains over
            several passes rather than in one long transaction.

    Returns:
        How many commissions were accrued.
    """
    rows = (
        await db.execute(
            select(Order, AffiliateAttribution, AffiliateCode)
            .join(AffiliateAttribution, AffiliateAttribution.user_id == Order.user_id)
            .join(AffiliateCode, AffiliateCode.id == AffiliateAttribution.code_id)
            .outerjoin(AffiliateCommission, AffiliateCommission.order_id == Order.id)
            .where(
                Order.status == "delivered",
                Order.delivered_at.isnot(None),
                # Wallet top-ups are 1:1 deposits, not sales. Paying commission
                # on one would pay a partner for the buyer moving their own
                # money, and would do it again on the order it then funds.
                Order.purpose == "catalog",
                AffiliateCommission.id.is_(None),
            )
            .order_by(Order.delivered_at)
            .limit(limit)
        )
    ).all()

    accrued = 0
    for order, attribution, code in rows:
        amount = commission_amount(order.total_charged, code.commission_percent, order.currency)
        if amount <= 0:
            continue
        commission = AffiliateCommission(
            id=new_id(),
            order_id=order.id,
            partner_id=attribution.partner_id,
            code_id=code.id,
            base_amount=order.total_charged,
            percent=code.commission_percent,
            amount=amount,
            currency=order.currency,
            status="pending",
            available_at=now() + timedelta(days=hold_days),
        )
        db.add(commission)
        try:
            # Settle the UNIQUE before posting: if a concurrent pass already
            # took this order, we must not put money in the ledger for it.
            await db.flush()
        except IntegrityError:
            await db.rollback()
            continue
        await post_accrual(
            db,
            commission_id=commission.id,
            partner_id=commission.partner_id,
            amount=amount,
            currency=order.currency,
            order_id=order.id,
        )
        accrued += 1

    if accrued:
        log.info("affiliate.accrual.accrued", count=accrued)
    return accrued


__all__ = ["accrue_commissions"]
```

- [ ] **Step 6: Run the tests**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_accrual.py -v`
Expected: PASS, 9 passed.

If `test_accrual_is_idempotent` fails because `db.rollback()` inside the loop discards the whole test transaction, replace the `try/except IntegrityError` block with a `SAVEPOINT`:

```python
        try:
            async with db.begin_nested():
                await db.flush()
        except IntegrityError:
            continue
```

`begin_nested` is the correct call here regardless — the outer transaction belongs to the caller and this function must not end it. Prefer it and only fall back if the codebase has an established alternative.

- [ ] **Step 7: Typecheck, lint, commit**

```bash
cd apps/api && uv run mypy src && uv run ruff check src tests && uv run ruff format --check src tests
cd ../.. && git add apps/api/src/yupay/modules/affiliate apps/api/src/yupay/core/config.py apps/api/tests/integration/test_affiliate_accrual.py
git commit -m "feat(api/affiliate): accrue commission for delivered attributed orders

Idempotent by construction: UNIQUE(order_id) picks the winner and the ledger
posting is keyed off the commission row id, so overlapping passes cannot pay
twice and a missed order is picked up next time. Wallet top-ups are excluded —
paying commission on a 1:1 deposit would pay twice for the same money."
```

---

### Task 4: Mature commission after the hold period

**Files:**

- Modify: `apps/api/src/yupay/modules/affiliate/ledger.py`
- Modify: `apps/api/src/yupay/modules/affiliate/accrual.py`
- Test: `apps/api/tests/integration/test_affiliate_accrual.py`

**Interfaces:**

- Consumes: `post_accrual`, `accrue_commissions` from Task 3.
- Produces:
  - `affiliate.ledger.post_maturation(db, *, commission_id: str, partner_id: str, amount: Decimal, currency: str) -> None`
  - `affiliate.accrual.mature_commissions(db: AsyncSession, *, limit: int = 500) -> int`

- [ ] **Step 1: Write the failing test**

Append to `apps/api/tests/integration/test_affiliate_accrual.py`:

```python
async def test_maturation_moves_pending_to_balance(db_session: AsyncSession) -> None:
    """Past its hold date, commission becomes withdrawable — and 'withdrawable'
    is the balance of ``partner_balance``, not a sum over the table."""
    from sqlalchemy import select, update
    from yupay.core.clock import now
    from yupay.modules.affiliate.accrual import accrue_commissions, mature_commissions
    from yupay.modules.affiliate.models import AffiliateCommission

    _, partner_id, _ = await _seed_delivered_order(db_session, total_charged=Decimal("100000"))
    assert await accrue_commissions(db_session, hold_days=14) == 1

    # Nothing is due yet.
    assert await mature_commissions(db_session) == 0

    await db_session.execute(
        update(AffiliateCommission).values(available_at=now() - timedelta(seconds=1))
    )
    assert await mature_commissions(db_session) == 1
    assert await mature_commissions(db_session) == 0

    row = (await db_session.execute(select(AffiliateCommission))).scalar_one()
    assert row.status == "available"

    pending = await wallet_service.ensure_account(
        db_session,
        owner_type="partner",
        owner_id=partner_id,
        kind="partner_pending",
        currency="UZS",
    )
    balance = await wallet_service.ensure_account(
        db_session,
        owner_type="partner",
        owner_id=partner_id,
        kind="partner_balance",
        currency="UZS",
    )
    assert await wallet_service.balance(db_session, pending.id) == Decimal("0")
    assert await wallet_service.balance(db_session, balance.id) == Decimal("2000")
```

Add `from datetime import timedelta` to the test module's imports.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_accrual.py::test_maturation_moves_pending_to_balance -v`
Expected: FAIL with `ImportError: cannot import name 'mature_commissions'`.

- [ ] **Step 3: Add the maturation posting**

In `apps/api/src/yupay/modules/affiliate/ledger.py`, add after `post_accrual` and extend `__all__` to `["commission_amount", "post_accrual", "post_maturation"]`:

```python
async def post_maturation(
    db: AsyncSession,
    *,
    commission_id: str,
    partner_id: str,
    amount: Decimal,
    currency: str,
) -> None:
    """Release held commission: ``D partner_balance / C partner_pending``.

    Both accounts belong to the partner, so this moves nothing in or out of the
    business — it only changes what the partner is allowed to withdraw.
    """
    pending = await _partner_account(
        db, partner_id=partner_id, kind="partner_pending", currency=currency
    )
    balance = await _partner_account(
        db, partner_id=partner_id, kind="partner_balance", currency=currency
    )
    await wallet_service.post(
        db,
        kind="affiliate.mature",
        legs=[
            wallet_service.Leg(account_id=balance, direction="D", amount=amount, currency=currency),
            wallet_service.Leg(account_id=pending, direction="C", amount=amount, currency=currency),
        ],
        idempotency_key=f"affiliate.mature:{commission_id}",
        actor="scheduler",
    )
```

- [ ] **Step 4: Add the maturation sweep**

In `apps/api/src/yupay/modules/affiliate/accrual.py`, import `post_maturation` alongside `post_accrual`, add the function below `accrue_commissions`, and extend `__all__` to `["accrue_commissions", "mature_commissions"]`:

```python
async def mature_commissions(db: AsyncSession, *, limit: int = 500) -> int:
    """Release commissions whose hold period has expired.

    Args:
        db: Session. The caller owns the transaction.
        limit: Maximum rows handled in one pass.

    Returns:
        How many commissions became available.
    """
    moment = now()
    rows = (
        await db.execute(
            select(AffiliateCommission)
            .where(
                AffiliateCommission.status == "pending",
                AffiliateCommission.available_at <= moment,
            )
            .order_by(AffiliateCommission.available_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).scalars()

    matured = 0
    for commission in rows:
        await post_maturation(
            db,
            commission_id=commission.id,
            partner_id=commission.partner_id,
            amount=commission.amount,
            currency=commission.currency,
        )
        commission.status = "available"
        matured += 1

    if matured:
        log.info("affiliate.accrual.matured", count=matured)
    return matured
```

`with_for_update(skip_locked=True)` is what keeps two overlapping passes from both maturing the same row; the deterministic idempotency key on the posting is the second line of defence.

- [ ] **Step 5: Run the tests**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_accrual.py -v`
Expected: PASS, 10 passed.

- [ ] **Step 6: Typecheck, lint, commit**

```bash
cd apps/api && uv run mypy src && uv run ruff check src tests && uv run ruff format --check src tests
cd ../.. && git add apps/api/src/yupay/modules/affiliate apps/api/tests/integration/test_affiliate_accrual.py
git commit -m "feat(api/affiliate): mature held commission into the withdrawable balance

'Available to withdraw' is now literally the balance of partner_balance, so
the panel and the payout check read one number from one place."
```

---

### Task 5: Void commission on refund

**Files:**

- Modify: `apps/api/src/yupay/modules/affiliate/ledger.py`
- Modify: `apps/api/src/yupay/modules/affiliate/accrual.py`
- Create: `apps/api/src/yupay/modules/affiliate/api.py`
- Test: `apps/api/tests/integration/test_affiliate_accrual.py`

**Interfaces:**

- Consumes: everything from Tasks 3 and 4.
- Produces:
  - `affiliate.accrual.void_commission(db: AsyncSession, *, order_id: str) -> bool`
  - `yupay.modules.affiliate.api` re-exporting `accrue_commissions`, `mature_commissions`, `void_commission`. **Every other module and the scheduler import from `api`, never from `accrual` directly.**

- [ ] **Step 1: Write the failing test**

Append to `apps/api/tests/integration/test_affiliate_accrual.py`:

```python
async def test_void_reverses_a_pending_commission(db_session: AsyncSession) -> None:
    """A refund before maturity takes the money back out of pending."""
    from sqlalchemy import select
    from yupay.modules.affiliate import api as affiliate_api
    from yupay.modules.affiliate.models import AffiliateCommission

    order_id, partner_id, _ = await _seed_delivered_order(
        db_session, total_charged=Decimal("100000")
    )
    assert await affiliate_api.accrue_commissions(db_session, hold_days=14) == 1

    assert await affiliate_api.void_commission(db_session, order_id=order_id) is True

    row = (await db_session.execute(select(AffiliateCommission))).scalar_one()
    assert row.status == "void"

    pending = await wallet_service.ensure_account(
        db_session,
        owner_type="partner",
        owner_id=partner_id,
        kind="partner_pending",
        currency="UZS",
    )
    assert await wallet_service.balance(db_session, pending.id) == Decimal("0")

    # Voiding again is a no-op, not a second reversal.
    assert await affiliate_api.void_commission(db_session, order_id=order_id) is False
    assert await wallet_service.balance(db_session, pending.id) == Decimal("0")


async def test_void_refuses_an_already_matured_commission(db_session: AsyncSession) -> None:
    """After maturity the money may already be in a payout request, so an
    automatic clawback is refused and left to an admin."""
    from sqlalchemy import select, update
    from yupay.core.clock import now
    from yupay.modules.affiliate import api as affiliate_api
    from yupay.modules.affiliate.models import AffiliateCommission

    order_id, _, _ = await _seed_delivered_order(db_session, total_charged=Decimal("100000"))
    assert await affiliate_api.accrue_commissions(db_session, hold_days=14) == 1
    await db_session.execute(
        update(AffiliateCommission).values(available_at=now() - timedelta(seconds=1))
    )
    assert await affiliate_api.mature_commissions(db_session) == 1

    assert await affiliate_api.void_commission(db_session, order_id=order_id) is False
    row = (await db_session.execute(select(AffiliateCommission))).scalar_one()
    assert row.status == "available"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_accrual.py -v -k void`
Expected: FAIL with `ModuleNotFoundError: No module named 'yupay.modules.affiliate.api'`.

- [ ] **Step 3: Add the reversal posting**

In `apps/api/src/yupay/modules/affiliate/ledger.py`, add and extend `__all__` to include `"post_void"`:

```python
async def post_void(
    db: AsyncSession,
    *,
    commission_id: str,
    partner_id: str,
    amount: Decimal,
    currency: str,
) -> None:
    """Reverse an accrual: ``C partner_pending / D house_affiliate_expense``.

    The mirror image of :func:`post_accrual`, and only valid while the money is
    still held. Once matured it may already be reserved by a payout request,
    which is why :func:`~yupay.modules.affiliate.accrual.void_commission`
    refuses that case rather than posting this.
    """
    pending = await _partner_account(
        db, partner_id=partner_id, kind="partner_pending", currency=currency
    )
    expense = await _house_account(db, kind="house_affiliate_expense", currency=currency)
    await wallet_service.post(
        db,
        kind="affiliate.void",
        legs=[
            wallet_service.Leg(account_id=expense, direction="D", amount=amount, currency=currency),
            wallet_service.Leg(account_id=pending, direction="C", amount=amount, currency=currency),
        ],
        idempotency_key=f"affiliate.void:{commission_id}",
        actor="system",
    )
```

- [ ] **Step 4: Add `void_commission`**

In `apps/api/src/yupay/modules/affiliate/accrual.py`, import `post_void`, add the function, and extend `__all__` to `["accrue_commissions", "mature_commissions", "void_commission"]`:

```python
async def void_commission(db: AsyncSession, *, order_id: str) -> bool:
    """Reverse the commission on a refunded order, if it is still held.

    Args:
        db: Session. The caller owns the transaction.
        order_id: The order that was refunded or cancelled.

    Returns:
        ``True`` if a commission was reversed; ``False`` if there was none, or
        it had already matured, or it was already void. A matured commission is
        deliberately left alone — it may already sit inside a payout request,
        and clawing back money a partner can see is an admin's decision, not a
        sweep's. See the spec's "Refunds" note.
    """
    commission = (
        await db.execute(
            select(AffiliateCommission)
            .where(AffiliateCommission.order_id == order_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if commission is None or commission.status != "pending":
        return False

    await post_void(
        db,
        commission_id=commission.id,
        partner_id=commission.partner_id,
        amount=commission.amount,
        currency=commission.currency,
    )
    commission.status = "void"
    log.info("affiliate.accrual.voided", order_id=order_id)
    return True
```

- [ ] **Step 5: Write the module facade**

Create `apps/api/src/yupay/modules/affiliate/api.py`:

```python
"""Public interface of the ``affiliate`` module.

Other modules and the scheduler import from here, never from ``accrual`` or
``ledger`` directly — the same rule the rest of the codebase follows, and what
lets the internals move without a cross-module edit.
"""

from __future__ import annotations

from yupay.modules.affiliate.accrual import (
    accrue_commissions,
    mature_commissions,
    void_commission,
)

__all__ = ["accrue_commissions", "mature_commissions", "void_commission"]
```

- [ ] **Step 6: Run the full module test file**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_accrual.py -v`
Expected: PASS, 12 passed.

- [ ] **Step 7: Check coverage against the 95% gate**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_accrual.py --cov=yupay.modules.affiliate --cov-report=term-missing`
Expected: ≥ 95% for `yupay/modules/affiliate/*`. If a branch is uncovered, add a test for it — do not lower the gate.

- [ ] **Step 8: Typecheck, lint, commit**

```bash
cd apps/api && uv run mypy src && uv run ruff check src tests && uv run ruff format --check src tests
cd ../.. && git add apps/api/src/yupay/modules/affiliate apps/api/tests/integration/test_affiliate_accrual.py
git commit -m "feat(api/affiliate): reverse commission on a refund before maturity

Refuses to touch matured commission: it may already sit inside a payout
request, and clawing back money a partner can see is an admin's call."
```

---

### Task 6: Scheduler job, documentation and ADR

**Files:**

- Create: `apps/scheduler/src/yupay_scheduler/jobs/affiliate_accrual.py`
- Modify: `apps/scheduler/src/yupay_scheduler/main.py:36-53` (imports) and `:71-82` (registrations)
- Create: `apps/api/src/yupay/modules/affiliate/README.md`
- Create: `docs/decisions/0061-affiliate-commission-by-sweep.md`
- Modify: `docs/architecture/module-map.md`

**Interfaces:**

- Consumes: `yupay.modules.affiliate.api.accrue_commissions` and `.mature_commissions`.
- Produces: `affiliate_accrual.register(scheduler: AsyncIOScheduler) -> None` and `affiliate_accrual.run_affiliate_accrual() -> None`.

- [ ] **Step 1: Write the job**

Create `apps/scheduler/src/yupay_scheduler/jobs/affiliate_accrual.py`:

```python
"""Accrue and mature affiliate commission.

Two steps in one tick, in one transaction: accrue what is newly delivered,
then release what has finished its hold period. Both are idempotent, so a tick
that dies halfway costs nothing but a retry.

Five minutes rather than on-delivery. Commission sits behind a two-week hold
before a partner can withdraw it, so freshness is worth almost nothing here —
and the fulfilment path it would otherwise hang off is the slowest in the
system, the one where a customer is waiting for a code.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import get_logger
from yupay.modules.affiliate import api as affiliate_api

from yupay_scheduler.startup import first_run_after

log = get_logger("yupay.scheduler.affiliate_accrual")

_JOB_ID = "affiliate.accrual"


async def run_affiliate_accrual() -> None:
    """One scheduler tick, in its own session/transaction."""
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            accrued = await affiliate_api.accrue_commissions(
                session,
                hold_days=settings.affiliate_hold_days,
                limit=settings.affiliate_sweep_batch,
            )
            matured = await affiliate_api.mature_commissions(
                session, limit=settings.affiliate_sweep_batch
            )
    if accrued or matured:
        log.info("affiliate.accrual.tick", accrued=accrued, matured=matured)


def register(scheduler: AsyncIOScheduler) -> None:
    """Attach the job to ``scheduler``."""
    settings = get_settings()
    scheduler.add_job(
        run_affiliate_accrual,
        trigger="interval",
        minutes=settings.affiliate_sweep_minutes,
        id=_JOB_ID,
        # Explicit first run: without it the first tick is a whole interval
        # after boot, and a container restarting more often than its own period
        # never runs the job at all. Offset so it does not land with the other
        # sweeps on every deploy.
        next_run_time=first_run_after(90),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("affiliate.accrual.registered", interval_minutes=settings.affiliate_sweep_minutes)


__all__ = ["register", "run_affiliate_accrual"]
```

Check whether the settings accessor in this codebase is `get_settings()` — run `grep -rn "def get_settings\|from yupay.core.config import" apps/scheduler/src | head`. If the other jobs obtain settings differently, follow their pattern instead.

- [ ] **Step 2: Register it**

In `apps/scheduler/src/yupay_scheduler/main.py`, add `affiliate_accrual,` to the `from yupay_scheduler.jobs import (...)` block (alphabetically first, before `broadcast_dispatch`), and add `affiliate_accrual.register(scheduler)` as the first registration inside `build_scheduler()`.

- [ ] **Step 3: Verify the scheduler still builds**

Run: `cd apps/scheduler && uv run python -c "from yupay_scheduler.main import build_scheduler; s = build_scheduler(); print([j.id for j in s.get_jobs()])"`
Expected: a list of job ids including `affiliate.accrual`.

- [ ] **Step 4: Write the module README**

Create `apps/api/src/yupay/modules/affiliate/README.md`:

````markdown
# `affiliate`

Partner program: a partner promotes a code, buyers get 3–10% off their first
order and are permanently attributed to that partner, and the partner earns
1–2% of every subsequent order.

**Spec:** `docs/superpowers/specs/2026-08-27-affiliate-program-design.md`
**ADR:** `docs/decisions/0061-affiliate-commission-by-sweep.md`

## Why this is not part of `promo`

`promo` credits a fixed gift **to the buyer's wallet, after payment**
(`D user_wallet / C house_promo_expense`). An affiliate code **reduces what the
buyer pays, before payment**, and binds them to a partner. Different moment,
different postings, different ownership.

## Money

| Event                                    | Posting                                          |
| ---------------------------------------- | ------------------------------------------------ |
| Commission accrued                       | `D partner_pending / C house_affiliate_expense`  |
| Hold period expired                      | `D partner_balance / C partner_pending`          |
| Payout requested                         | `D partner_payout_hold / C partner_balance`      |
| Payout transferred                       | `D house_affiliate_paid / C partner_payout_hold` |
| Payout rejected                          | `D partner_balance / C partner_payout_hold`      |
| Commission voided (refund, pre-maturity) | `D house_affiliate_expense / C partner_pending`  |

**"Available to withdraw" is the balance of `partner_balance`** — not a sum
computed over `affiliate_commissions`. One source of truth, and a payout
request that reserves its money cannot be raced into an overdraft.

There is no posting for the discount, and there must not be one. The buyer
simply pays less; cost of goods is unchanged, so our margin is genuinely lower.
That is a fact about revenue, not an expense.

## The two constraints that carry the design

- `UNIQUE(user_id)` on `affiliate_attributions` — a buyer belongs to one
  partner, forever, guaranteed by the database.
- `UNIQUE(order_id)` on `affiliate_commissions` — the accrual sweep's entire
  idempotency. Overlapping ticks cannot pay twice; a missed order is picked up
  next pass; nothing needs reconciling by hand.

## Public interface

Import from `api`, never from `accrual` or `ledger`:

```python
from yupay.modules.affiliate import api as affiliate_api

await affiliate_api.accrue_commissions(db, hold_days=14, limit=500)  # -> int
await affiliate_api.mature_commissions(db, limit=500)                # -> int
await affiliate_api.void_commission(db, order_id=order_id)           # -> bool
```

`void_commission` deliberately refuses a matured commission — it may already
sit inside a payout request, and clawing back money a partner can see is an
admin's decision.
````

- [ ] **Step 5: Write the ADR**

`0061` is the next free number (verified 2026-08-27: `0060-storefront-edge-caching.md` is the highest). Confirm with `ls docs/decisions/ | sort | tail -3` before writing, and if something has landed in the meantime, take the next one and update every reference to it in this task.

Create `docs/decisions/0061-affiliate-commission-by-sweep.md` using the MADR template at `docs/decisions/0000-template.md`. Content:

- **Context:** commission must be paid on every delivered order of an attributed buyer. The obvious place is the fulfilment transaction that marks the order delivered.
- **Decision:** accrue from a scheduled sweep every 5 minutes instead.
- **Consequences, positive:** idempotent by construction via `UNIQUE(order_id)`; a missed order is picked up by the next pass, so there is no reconciliation job and no lost partner money; the fulfilment path — already the slowest in the system, and the one where a customer waits for a code — gains no work; the sweep can be run by hand to repair any backlog.
- **Consequences, negative:** commission appears in the partner panel minutes late rather than instantly. This costs nothing: a two-week hold period sits in front of withdrawal either way.
- **Alternatives considered:** inline accrual in the delivery transaction (rejected — couples the money path to affiliate logic and lengthens the slowest path); a Dramatiq task enqueued on delivery (rejected for now — the worker has no actors yet, and an enqueue that fails silently is exactly the lost-money failure the sweep design avoids).

- [ ] **Step 6: Update the module map**

In `docs/architecture/module-map.md`, add `affiliate` with its edges: depends on `wallet` (postings) and `orders` (reads delivered orders); read by `scheduler`. Follow whatever notation the file already uses.

- [ ] **Step 7: Run the full backend suite**

Run: `cd apps/api && uv run pytest -q`
Expected: no failures. This is the check that the five new `NORMAL_SIDE` entries did not disturb any existing ledger assertion.

- [ ] **Step 8: Format the docs and commit**

```bash
npx prettier --check docs apps/api/src/yupay/modules/affiliate/README.md || npx prettier --write docs apps/api/src/yupay/modules/affiliate/README.md
git add apps/scheduler docs apps/api/src/yupay/modules/affiliate/README.md
git commit -m "feat(scheduler/affiliate): run the commission sweep every five minutes

Accrue then mature, in one transaction, both idempotent. ADR-0061 records why
this is a sweep rather than inline accrual in the delivery transaction: a
missed enqueue would be a partner's lost money, and the delivery path is the
one where a customer is waiting."
```

---

## Definition of Done for this plan

- [ ] `cd apps/api && uv run pytest -q` passes.
- [ ] Coverage of `yupay/modules/affiliate/*` is ≥ 95%.
- [ ] `uv run ruff check src tests migrations` and `uv run ruff format --check src tests migrations` clean.
- [ ] `uv run mypy src` reports **no more errors than the baseline on `main`** (1026 in 179 files as of 2026-08-27 — `CLAUDE.md` claims `mypy --strict` is clean, and it is not). Compare with `git stash`, do not chase the pre-existing ones.
- [ ] `npx prettier --check .` clean (CI's `lint-ts` fails on unformatted markdown, docs included).
- [ ] `alembic downgrade 0055_admin_list_sort_indexes` then `alembic upgrade head` both succeed.
- [ ] The scheduler builds and lists `affiliate.accrual`.
- [ ] Module `README.md`, ADR-0061 and `module-map.md` are all updated.
- [ ] No `TODO`/`FIXME` without a tracked issue link.
- [ ] Nothing is pushed or deployed — this repository requires an explicit instruction for both.

## Not in this plan

Covered by plans 2–7: the discount on the order path and `order_items.discount_usd`; attribution creation at payment; the checkout promo field; partner authentication and the panel API; `apps/partners`; admin screens; DNS, Caddy, CI and deploy.

`AffiliatePayout` and `AffiliateSession` are created here as tables but nothing writes to them until plan 4. That is deliberate — one migration for the feature's schema is easier to review and to roll back than six.
