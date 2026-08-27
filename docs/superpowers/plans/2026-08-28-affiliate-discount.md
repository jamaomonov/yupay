# Affiliate discount on the order path — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an affiliate code reduce what a buyer pays, bind that buyer to the partner when the order is paid, and keep the margin reports honest about it.

**Architecture:** A new `affiliate.discount` module owns the six admission conditions and the arithmetic. `orders.create_order` calls it between computing the total and persisting the order; the client never sends a price. Attribution is written in the transaction that marks the order paid, guarded by `UNIQUE(user_id)`. The discount is distributed across order lines so the existing line-level revenue expressions can subtract it once and every report becomes correct.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, pytest + testcontainers.

**Spec:** `docs/superpowers/specs/2026-08-27-affiliate-program-design.md`
**Previous plan:** `docs/superpowers/plans/2026-08-27-affiliate-core.md` (step 1 — schema, ledger, accrual sweep)

**Plan 2 of 7.** Steps 3–7 remain: the checkout promo field, partner auth and panel API, `apps/partners`, admin screens, infrastructure.

## Global Constraints

Same as plan 1, which see. The ones that bit during step 1 and are worth repeating:

- **Alembic revision ids are capped at 32 characters**, and a longer one fails at the very end of `upgrade`, after the body has run.
- **Import `wallet.service`, not `wallet.api`** — the facade drags in the whole v1 route stack. Same for any other module facade that mounts a router.
- **`mypy --strict` is not clean on `main`** (1026 errors baseline as of 2026-08-27, mostly the untyped `Base`). Compare against the baseline with `git stash`; do not chase pre-existing errors. A `-> str` function returning `account.id` **is** a new error — return the model object instead.
- Coverage gate for this module is **95%**.
- Money is `Decimal`, never float. Never log PII.
- Commit after every green test run. **Do not push or deploy** without an explicit instruction.

## Correction to the spec

The spec says the margin fix is to have `charged_usd_expr()` subtract the discount. That is half of it. `margin_usd_expr()` computes margin independently of `charged_usd_expr()`, and the invariant is `gross − margin == cost`. A discount reduces both revenue and margin by the same amount and leaves cost alone:

```
(gross − discount) − (margin − discount) == cost
```

So **both** expressions subtract `COALESCE(order_items.discount_usd, 0)`. Subtracting in only one would break the invariant and overstate margin by exactly the discount.

## File Structure

**Created:**

| File                                                            | Responsibility                                                     |
| --------------------------------------------------------------- | ------------------------------------------------------------------ |
| `apps/api/src/yupay/modules/affiliate/discount.py`              | The six admission conditions and the discount arithmetic. No HTTP. |
| `apps/api/src/yupay/modules/affiliate/attribution.py`           | Binding a buyer to a partner at payment.                           |
| `apps/api/src/yupay/modules/affiliate/schemas.py`               | Preview request/response models.                                   |
| `apps/api/src/yupay/modules/affiliate/routes.py`                | The buyer-facing preview endpoint.                                 |
| `apps/api/migrations/versions/0058_order_affiliate_discount.py` | Three columns.                                                     |
| `apps/api/tests/integration/test_affiliate_discount.py`         | Admission conditions, arithmetic, attribution, analytics.          |

**Modified:**

| File                                             | Change                                                                         |
| ------------------------------------------------ | ------------------------------------------------------------------------------ |
| `apps/api/src/yupay/modules/affiliate/models.py` | Nothing — the discount lives on the order, not here.                           |
| `apps/api/src/yupay/modules/affiliate/api.py`    | Export the new entry points and the router.                                    |
| `apps/api/src/yupay/modules/orders/models.py`    | `Order.affiliate_code_id`, `Order.discount_charged`, `OrderItem.discount_usd`. |
| `apps/api/src/yupay/modules/orders/schemas.py`   | `OrderCreate.affiliate_code`, `OrderOut.discount_charged`.                     |
| `apps/api/src/yupay/modules/orders/service.py`   | Apply the discount between total computation and persistence.                  |
| `apps/api/src/yupay/modules/orders/revenue.py`   | Both expressions subtract the line discount.                                   |
| `apps/api/src/yupay/modules/payments/service.py` | Bind attribution where a catalog order becomes paid.                           |
| `apps/api/src/yupay/api/v1/__init__.py`          | Mount the affiliate router.                                                    |

---

### Task 1: Columns for the discount

**Files:**

- Modify: `apps/api/src/yupay/modules/orders/models.py`
- Create: `apps/api/migrations/versions/0058_order_affiliate_discount.py`
- Test: `apps/api/tests/integration/test_affiliate_discount.py`

**Interfaces:**

- Produces: `Order.affiliate_code_id: str | None`, `Order.discount_charged: Decimal` (default 0), `OrderItem.discount_usd: Decimal` (default 0).

`discount_charged` and `discount_usd` are `NOT NULL DEFAULT 0` rather than nullable: every existing order genuinely had no discount, and a zero is easier to sum than a NULL. `affiliate_code_id` is nullable because most orders have no code.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/integration/test_affiliate_discount.py`:

```python
"""Affiliate discount: admission, arithmetic, attribution, and the margin reports.

The reason this module exists at all is the last one. Revenue and margin are
computed from order lines, not from ``total_charged``, so a discount that only
reduced the payable total would be invisible to every report — full margin
shown on precisely the orders that have the least of it.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


def _unique_code(prefix: str) -> str:
    """A collision-free test code. Not derived from ``new_id()``: it is a
    UUIDv7, so its leading characters are a timestamp and codes minted inside
    one test share them."""
    return f"{prefix}{secrets.token_hex(5).upper()}"


async def test_order_carries_discount_columns(db_session: AsyncSession) -> None:
    """The three new columns exist and default to "no discount"."""
    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.orders.models import Order

    moment = now()
    order = Order(
        id=new_id(),
        guest_email=f"g-{new_id()}@example.test",
        status="pending_payment",
        currency="UZS",
        total_usd=Decimal("1"),
        total_charged=Decimal("12000"),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.refresh(order)

    assert order.affiliate_code_id is None
    assert order.discount_charged == Decimal("0")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_discount.py -v`
Expected: FAIL — `AttributeError: 'Order' object has no attribute 'affiliate_code_id'`.

- [ ] **Step 3: Add the columns to the models**

In `apps/api/src/yupay/modules/orders/models.py`, on `Order`, after `total_charged`:

```python
    #: The affiliate code applied at checkout, if any. Kept for the receipt and
    #: the order history; the money effect is already in ``total_charged``.
    affiliate_code_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("affiliate_codes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    #: How much the affiliate discount took off, in the order's currency.
    #: NOT NULL DEFAULT 0 rather than nullable — every order without a code
    #: genuinely had a zero discount, and a zero is easier to sum than a NULL.
    discount_charged: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, server_default=text("0"), default=Decimal("0")
    )
```

On `OrderItem`, after `unit_price_usd`:

```python
    #: This line's share of the order's affiliate discount, in USD.
    #:
    #: The discount is an order-level number, but revenue and margin are
    #: computed per line (``orders.revenue``). Distributing it here is what
    #: lets those expressions subtract it once and make every report — total,
    #: per brand, per product — correct without editing each one.
    discount_usd: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, server_default=text("0"), default=Decimal("0")
    )
```

- [ ] **Step 4: Write the migration**

Create `apps/api/migrations/versions/0058_order_affiliate_discount.py` (revision id is 30 characters — under the 32 cap):

```python
"""Affiliate discount columns on orders and order items.

``order_items.discount_usd`` is the load-bearing one. Revenue and margin are
computed from line-level ``unit_price_usd``/``rate_multiplier`` in
``orders/revenue.py``, not from ``orders.total_charged``, so a discount that
only reduced the payable total would be invisible to every report — the admin
would see full margin on exactly the orders that have the least of it, and
would not find out for weeks.

Distributing the discount across lines lets both revenue expressions subtract
it once, keeping ``gross - margin == cost`` true with the discount taken out of
both sides.

NOT NULL DEFAULT 0 rather than nullable: every order written before this
genuinely had no discount.

Revision ID: 0058_order_affiliate_discount
Revises: 0057_affiliate_program
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0058_order_affiliate_discount"
down_revision: str | None = "0057_affiliate_program"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("affiliate_code_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.create_foreign_key(
        "fk_orders_affiliate_code",
        "orders",
        "affiliate_codes",
        ["affiliate_code_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "orders",
        sa.Column(
            "discount_charged",
            sa.Numeric(20, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "order_items",
        sa.Column(
            "discount_usd", sa.Numeric(20, 6), nullable=False, server_default=sa.text("0")
        ),
    )


def downgrade() -> None:
    op.drop_column("order_items", "discount_usd")
    op.drop_column("orders", "discount_charged")
    op.drop_constraint("fk_orders_affiliate_code", "orders", type_="foreignkey")
    op.drop_column("orders", "affiliate_code_id")
```

- [ ] **Step 5: Run the test**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_discount.py -v`
Expected: PASS.

- [ ] **Step 6: Round-trip the migration against the dev database**

```bash
docker compose exec -T api alembic upgrade head
docker compose exec -T api alembic downgrade 0057_affiliate_program
docker compose exec -T api alembic upgrade head
docker compose exec -T api alembic current
```

Expected: all succeed, ending at `0058_order_affiliate_discount (head)`.

- [ ] **Step 7: Lint, typecheck, commit**

```bash
cd apps/api && uv run ruff check --fix src tests migrations && uv run ruff format src tests migrations
uv run mypy src | tail -1   # compare against baseline, do not chase pre-existing
cd ../.. && git add apps/api/src/yupay/modules/orders/models.py apps/api/migrations/versions/0058_order_affiliate_discount.py apps/api/tests/integration/test_affiliate_discount.py
git commit -m "feat(api/orders): columns for the affiliate discount

order_items.discount_usd is the load-bearing one: revenue and margin are
computed per line, not from total_charged, so a discount that only reduced the
payable total would show full margin on exactly the orders with the least."
```

---

### Task 2: The six admission conditions

**Files:**

- Create: `apps/api/src/yupay/modules/affiliate/discount.py`
- Test: `apps/api/tests/integration/test_affiliate_discount.py`

**Interfaces:**

- Produces:
  - `DiscountRejection` — a `Literal` of the reason codes the UI branches on: `"unknown"`, `"guest"`, `"already_used"`, `"not_first_order"`, `"own_code"`, `"pending_coded_order"`, `"not_catalog"`.
  - `ResolvedDiscount` — frozen model carrying `code_id`, `code`, `percent`.
  - `resolve_code(db, *, code: str, user_id: str | None, purpose: str) -> ResolvedDiscount | DiscountRejection`

`"unknown"` deliberately covers a code that does not exist, one that is inactive, and one whose partner is inactive. The spec requires the response not to reveal whether a code exists — otherwise the preview endpoint becomes a directory of other people's promo codes.

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/integration/test_affiliate_discount.py`. Put this helper above the tests:

```python
async def _seed_partner_and_code(
    db: AsyncSession,
    *,
    discount_percent: Decimal = Decimal("5"),
    active: bool = True,
    partner_status: str = "active",
    linked_user_id: str | None = None,
) -> tuple[str, str]:
    """Create a partner and one code.

    Returns:
        ``(code_id, code)``.
    """
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.models import AffiliateCode, AffiliatePartner

    partner = AffiliatePartner(
        id=new_id(),
        email=f"p-{new_id()}@example.test",
        status=partner_status,
        user_id=linked_user_id,
    )
    db.add(partner)
    await db.flush()

    code = AffiliateCode(
        id=new_id(),
        partner_id=partner.id,
        code=_unique_code("C"),
        discount_percent=discount_percent,
        commission_percent=Decimal("2"),
        active=active,
    )
    db.add(code)
    await db.flush()
    return code.id, code.code


async def _new_user(db: AsyncSession) -> str:
    from yupay.core.ids import new_id
    from yupay.modules.users.models import User

    user = User(id=new_id())
    db.add(user)
    await db.flush()
    return user.id


async def test_resolve_accepts_a_valid_code_for_a_fresh_buyer(
    db_session: AsyncSession,
) -> None:
    from yupay.modules.affiliate.discount import ResolvedDiscount, resolve_code

    _, code = await _seed_partner_and_code(db_session, discount_percent=Decimal("7"))
    user_id = await _new_user(db_session)

    result = await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog")
    assert isinstance(result, ResolvedDiscount)
    assert result.percent == Decimal("7")


async def test_resolve_normalises_case_and_whitespace(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate.discount import ResolvedDiscount, resolve_code

    _, code = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)

    result = await resolve_code(
        db_session, code=f"  {code.lower()} ", user_id=user_id, purpose="catalog"
    )
    assert isinstance(result, ResolvedDiscount)


async def test_resolve_rejects_a_guest(db_session: AsyncSession) -> None:
    from yupay.modules.affiliate.discount import resolve_code

    _, code = await _seed_partner_and_code(db_session)
    assert await resolve_code(db_session, code=code, user_id=None, purpose="catalog") == "guest"


async def test_resolve_rejects_a_wallet_topup(db_session: AsyncSession) -> None:
    """A top-up is a 1:1 deposit. Discounting one prints money."""
    from yupay.modules.affiliate.discount import resolve_code

    _, code = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)
    assert (
        await resolve_code(db_session, code=code, user_id=user_id, purpose="wallet_topup")
        == "not_catalog"
    )


async def test_resolve_hides_whether_an_unusable_code_exists(db_session: AsyncSession) -> None:
    """Nonexistent, inactive, and suspended-partner codes are indistinguishable.

    Otherwise the preview endpoint is a directory of other people's codes.
    """
    from yupay.modules.affiliate.discount import resolve_code

    user_id = await _new_user(db_session)
    _, inactive = await _seed_partner_and_code(db_session, active=False)
    _, suspended = await _seed_partner_and_code(db_session, partner_status="suspended")

    for candidate in (_unique_code("Z"), inactive, suspended):
        assert (
            await resolve_code(db_session, code=candidate, user_id=user_id, purpose="catalog")
            == "unknown"
        )


async def test_resolve_rejects_a_buyer_who_already_belongs_to_a_partner(
    db_session: AsyncSession,
) -> None:
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.discount import resolve_code
    from yupay.modules.affiliate.models import AffiliateAttribution, AffiliateCode

    code_id, code = await _seed_partner_and_code(db_session)
    other_code_id, other_code = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)

    existing = await db_session.get(AffiliateCode, other_code_id)
    assert existing is not None
    db_session.add(
        AffiliateAttribution(
            id=new_id(),
            user_id=user_id,
            partner_id=existing.partner_id,
            code_id=other_code_id,
        )
    )
    await db_session.flush()

    assert (
        await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog")
        == "already_used"
    )


async def test_resolve_rejects_a_buyer_with_a_prior_paid_order(
    db_session: AsyncSession,
) -> None:
    """Deliberately 'no prior *paid* order', not 'no prior order': an abandoned
    unpaid cart must not disqualify someone forever."""
    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.discount import ResolvedDiscount, resolve_code
    from yupay.modules.orders.models import Order

    _, code = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)
    moment = now()

    abandoned = Order(
        id=new_id(),
        user_id=user_id,
        status="expired",
        currency="UZS",
        total_usd=Decimal("1"),
        total_charged=Decimal("12000"),
        purpose="catalog",
        expires_at=moment - timedelta(days=1),
    )
    db_session.add(abandoned)
    await db_session.flush()

    # An abandoned order does not disqualify.
    assert isinstance(
        await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog"),
        ResolvedDiscount,
    )

    paid = Order(
        id=new_id(),
        user_id=user_id,
        status="paid",
        currency="UZS",
        total_usd=Decimal("1"),
        total_charged=Decimal("12000"),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
        paid_at=moment,
    )
    db_session.add(paid)
    await db_session.flush()

    assert (
        await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog")
        == "not_first_order"
    )


async def test_resolve_rejects_a_partner_using_their_own_code(
    db_session: AsyncSession,
) -> None:
    from yupay.modules.affiliate.discount import resolve_code

    user_id = await _new_user(db_session)
    _, code = await _seed_partner_and_code(db_session, linked_user_id=user_id)

    assert (
        await resolve_code(db_session, code=code, user_id=user_id, purpose="catalog")
        == "own_code"
    )


async def test_resolve_rejects_while_an_unpaid_coded_order_is_open(
    db_session: AsyncSession,
) -> None:
    """Narrows the spec's known gap: without this, a buyer could open two orders
    with two codes and pay both, taking two discounts for one attribution."""
    from yupay.core.clock import now
    from yupay.core.ids import new_id
    from yupay.modules.affiliate.discount import resolve_code
    from yupay.modules.orders.models import Order

    code_id, _ = await _seed_partner_and_code(db_session)
    _, second = await _seed_partner_and_code(db_session)
    user_id = await _new_user(db_session)
    moment = now()

    db_session.add(
        Order(
            id=new_id(),
            user_id=user_id,
            status="pending_payment",
            currency="UZS",
            total_usd=Decimal("1"),
            total_charged=Decimal("12000"),
            purpose="catalog",
            expires_at=moment + timedelta(days=1),
            affiliate_code_id=code_id,
        )
    )
    await db_session.flush()

    assert (
        await resolve_code(db_session, code=second, user_id=user_id, purpose="catalog")
        == "pending_coded_order"
    )
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_discount.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yupay.modules.affiliate.discount'`.

- [ ] **Step 3: Write the module**

Create `apps/api/src/yupay/modules/affiliate/discount.py`:

```python
"""Whether an affiliate code applies to this buyer, and by how much.

Six conditions, all checked on the server, all at order creation. The client
never sends a price — it does not today either — so the preview endpoint's
answer is for display only and the authoritative arithmetic happens here again
when the order is actually created.

The rejection reasons are a closed set because the checkout UI branches on
them, and they are deliberately lossy in one place: a code that does not exist,
one that is switched off, and one whose partner is suspended all come back as
``"unknown"``. Distinguishing them would turn the preview endpoint into a
lookup service for other people's promo codes.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.affiliate.models import AffiliateAttribution, AffiliateCode, AffiliatePartner
from yupay.modules.orders.models import Order

#: Why a code was refused. The checkout UI shows a different message for each,
#: so these strings are a contract with the frontend, not a log detail.
DiscountRejection = Literal[
    "unknown",
    "guest",
    "already_used",
    "not_first_order",
    "own_code",
    "pending_coded_order",
    "not_catalog",
]

#: Order states that mean the buyer has actually bought something before.
#: Deliberately not "any prior order": an abandoned unpaid cart must not
#: disqualify someone from their one first-order discount forever.
_PAID_STATUSES = ("paid", "fulfilling", "delivered")

#: An order still waiting to be paid that already carries a code. See
#: ``pending_coded_order``.
_OPEN_STATUSES = ("pending_payment",)

#: Smallest payable unit per currency, mirroring ``affiliate.ledger``. UZS has
#: no subunit in practice — Payme and Click both reject fractions.
_QUANTUM: dict[str, Decimal] = {"UZS": Decimal("1")}
_DEFAULT_QUANTUM = Decimal("0.01")


class ResolvedDiscount(BaseModel):
    """An affiliate code that applies to this buyer."""

    model_config = ConfigDict(frozen=True)

    code_id: str
    code: str
    percent: Decimal


def normalise(code: str) -> str:
    """Uppercase and strip, the way the codes are stored."""
    return code.strip().upper()


def discount_amount(total: Decimal, percent: Decimal, currency: str) -> Decimal:
    """The discount on ``total``, rounded to a payable amount.

    Args:
        total: The order total before the discount, in ``currency``.
        percent: The code's discount percentage, e.g. ``Decimal("7")``.
        currency: ISO-4217 code, used to pick the rounding quantum.

    Returns:
        The amount to take off, quantized so the buyer sees a whole number and
        the acquirers accept it.
    """
    quantum = _QUANTUM.get(currency.upper(), _DEFAULT_QUANTUM)
    return (total * percent / Decimal(100)).quantize(quantum, rounding=ROUND_HALF_UP)


async def resolve_code(
    db: AsyncSession, *, code: str, user_id: str | None, purpose: str
) -> ResolvedDiscount | DiscountRejection:
    """Decide whether ``code`` applies to this buyer.

    Args:
        db: Session.
        code: What the buyer typed; normalised here.
        user_id: The signed-in buyer, or ``None`` for a guest.
        purpose: The order's purpose — only ``catalog`` orders qualify.

    Returns:
        A :class:`ResolvedDiscount`, or one of :data:`DiscountRejection`.
    """
    # Cheap, local checks first, so a guest typing a code never touches the DB.
    if purpose != "catalog":
        return "not_catalog"
    if user_id is None:
        return "guest"

    row = (
        await db.execute(
            select(AffiliateCode, AffiliatePartner)
            .join(AffiliatePartner, AffiliatePartner.id == AffiliateCode.partner_id)
            .where(AffiliateCode.code == normalise(code))
        )
    ).first()
    if row is None:
        return "unknown"
    affiliate_code, partner = row
    if not affiliate_code.active or partner.status != "active":
        return "unknown"

    if partner.user_id is not None and partner.user_id == user_id:
        return "own_code"

    already_bound = await db.scalar(
        select(exists().where(AffiliateAttribution.user_id == user_id))
    )
    if already_bound:
        return "already_used"

    has_paid_order = await db.scalar(
        select(
            exists().where(
                Order.user_id == user_id,
                Order.purpose == "catalog",
                Order.status.in_(_PAID_STATUSES),
            )
        )
    )
    if has_paid_order:
        return "not_first_order"

    # Narrows the race described in the spec: without this a buyer could open
    # two orders carrying two different codes and pay both, taking two
    # discounts against one attribution.
    has_open_coded_order = await db.scalar(
        select(
            exists().where(
                Order.user_id == user_id,
                Order.affiliate_code_id.isnot(None),
                Order.status.in_(_OPEN_STATUSES),
            )
        )
    )
    if has_open_coded_order:
        return "pending_coded_order"

    return ResolvedDiscount(
        code_id=affiliate_code.id,
        code=affiliate_code.code,
        percent=affiliate_code.discount_percent,
    )


def distribute_discount_usd(
    line_totals_usd: list[Decimal], discount_usd: Decimal
) -> list[Decimal]:
    """Split an order-level USD discount across its lines, proportionally.

    The rounding remainder goes to the largest line rather than being dropped,
    so the parts sum to exactly ``discount_usd``. Most orders here are single
    line, where this is the identity.

    Args:
        line_totals_usd: Each line's gross USD value, in order.
        discount_usd: The whole discount to distribute.

    Returns:
        One share per line, in the same order, summing to ``discount_usd``.
    """
    if not line_totals_usd:
        return []
    gross = sum(line_totals_usd)
    if gross <= 0:
        return [Decimal("0") for _ in line_totals_usd]

    cent = Decimal("0.000001")
    shares = [
        (discount_usd * total / gross).quantize(cent, rounding=ROUND_HALF_UP)
        for total in line_totals_usd
    ]
    remainder = discount_usd - sum(shares)
    if remainder:
        biggest = line_totals_usd.index(max(line_totals_usd))
        shares[biggest] += remainder
    return shares


__all__ = [
    "DiscountRejection",
    "ResolvedDiscount",
    "discount_amount",
    "distribute_discount_usd",
    "normalise",
    "resolve_code",
]
```

Note the unused import guard: `func` is imported above but may not be needed — remove it if ruff flags it.

- [ ] **Step 4: Run the tests**

Run: `cd apps/api && uv run pytest tests/integration/test_affiliate_discount.py -v`
Expected: PASS, 10 passed.

- [ ] **Step 5: Add a test for the distribution arithmetic**

Append:

```python
def test_distribute_discount_splits_proportionally_and_loses_nothing() -> None:
    """The parts must sum to the whole — a dropped remainder is money that
    silently reappears as margin."""
    from yupay.modules.affiliate.discount import distribute_discount_usd

    shares = distribute_discount_usd(
        [Decimal("10"), Decimal("20"), Decimal("30")], Decimal("6")
    )
    assert sum(shares) == Decimal("6")
    assert shares[2] > shares[0]


def test_distribute_discount_handles_one_line_and_no_lines() -> None:
    from yupay.modules.affiliate.discount import distribute_discount_usd

    assert distribute_discount_usd([Decimal("10")], Decimal("1")) == [Decimal("1")]
    assert distribute_discount_usd([], Decimal("1")) == []
    assert distribute_discount_usd([Decimal("0")], Decimal("1")) == [Decimal("0")]
```

These two are synchronous — mark them so pytest-asyncio does not adopt them, or move them into a `class TestDistribution:` if `pytestmark` at module level interferes. Run and confirm.

- [ ] **Step 6: Lint, typecheck, commit**

```bash
cd apps/api && uv run ruff check --fix src tests && uv run ruff format src tests
uv run mypy src | tail -1
cd ../.. && git add apps/api/src/yupay/modules/affiliate apps/api/tests/integration/test_affiliate_discount.py
git commit -m "feat(api/affiliate): the six admission conditions for a partner code

Nonexistent, disabled, and suspended-partner codes all answer 'unknown' on
purpose: distinguishing them turns the preview endpoint into a lookup service
for other people's promo codes.

'No prior paid order', not 'no prior order' -- an abandoned cart must not cost
someone their one first-order discount."
```

---

### Task 3: Apply the discount when the order is created

**Files:**

- Modify: `apps/api/src/yupay/modules/orders/schemas.py`
- Modify: `apps/api/src/yupay/modules/orders/service.py` (between step 3 and step 4 of `create_order`)
- Modify: `apps/api/src/yupay/modules/affiliate/api.py`
- Test: `apps/api/tests/integration/test_affiliate_discount.py`

**Interfaces:**

- Consumes: `resolve_code`, `discount_amount`, `distribute_discount_usd`.
- Produces: `OrderCreate.affiliate_code: str | None`; `OrderOut.discount_charged: Decimal`.

**Rejection policy at order creation:** a code that does not resolve is **ignored**, not an error — the order is created at full price. The buyer saw the verdict at preview time; failing the whole checkout because a code expired in the last thirty seconds would lose a sale over a discount. The applied code (or its absence) is visible in the response, so the frontend can tell the buyer what happened.

- [ ] **Step 1: Write the failing test**

```python
async def test_create_order_applies_the_discount(db_session: AsyncSession) -> None:
    """The server prices the order; the client only names a code."""
    # Build a catalog fixture (brand/product/sku) the same way
    # tests/integration/test_promo_routes.py does, create an order through
    # orders.service.create_order with affiliate_code set, and assert:
    #   order.total_charged == full_price - discount_amount(full_price, pct, cur)
    #   order.discount_charged == discount_amount(...)
    #   order.affiliate_code_id == code_id
    #   sum(i.discount_usd for i in order.items) == the USD discount
```

Write this out fully against the catalog helpers already used in
`tests/integration/test_promo_routes.py` — do not leave it as a comment.

- [ ] **Step 2: Add the request/response fields**

In `apps/api/src/yupay/modules/orders/schemas.py`, on `OrderCreate`:

```python
    #: An affiliate partner's code, as typed. Validated server-side; an
    #: unusable code is ignored rather than failing the order — the buyer
    #: already saw the verdict at preview time, and losing a sale over a
    #: discount that expired thirty seconds ago is the worse trade.
    affiliate_code: str | None = Field(default=None, max_length=32)
```

On `OrderOut`:

```python
    #: What the affiliate discount took off, in ``currency``. Zero when none.
    discount_charged: Decimal = Decimal("0")
```

- [ ] **Step 3: Apply it in `create_order`**

In `apps/api/src/yupay/modules/orders/service.py`, between the `_compute_total_charged` call (step 3) and the `Order(...)` construction (step 4):

```python
    # 3a) Affiliate discount. The client names a code; the server decides
    # whether it applies and by how much. An unusable code is ignored rather
    # than raising — see OrderCreate.affiliate_code.
    affiliate_code_id: str | None = None
    discount_charged = Decimal("0")
    if body.affiliate_code:
        resolved = await affiliate_api.resolve_code(
            db,
            code=body.affiliate_code,
            user_id=actor.user_id,
            # This function only ever builds catalog orders — a wallet
            # top-up is assembled in wallet/funding.py and never reaches
            # here. Passed explicitly so resolve_code's guard stays
            # meaningful for the preview endpoint, which any client can call.
            purpose="catalog",
        )
        if isinstance(resolved, ResolvedDiscount):
            discount_charged = affiliate_api.discount_amount(
                total_charged, resolved.percent, currency
            )
            total_charged -= discount_charged
            affiliate_code_id = resolved.code_id
            # The order-level discount has to reach the line level, or every
            # margin report keeps showing the pre-discount number.
            discount_usd_total = (total_usd * resolved.percent / Decimal(100)).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
            shares = affiliate_api.distribute_discount_usd(
                [item.unit_price_usd * item.qty for item in items], discount_usd_total
            )
            for item, share in zip(items, shares, strict=True):
                item.discount_usd = share
```

Then pass `affiliate_code_id=affiliate_code_id` and `discount_charged=discount_charged` into the `Order(...)` constructor, and add both to the `order.created` event payload.

Verified 2026-08-28: `OrderCreate` has no `purpose` field, and `create_order` never sets one — the model default `"catalog"` applies. Wallet top-up orders are built separately in `wallet/funding.py:124` with `purpose=PURPOSE_WALLET_TOPUP` and never pass through this function. So the literal above is correct, and `resolve_code`'s `not_catalog` branch exists for the preview endpoint, which any client can call with any purpose.

- [ ] **Step 4: Export from the module facade**

In `apps/api/src/yupay/modules/affiliate/api.py`, add `discount_amount`, `distribute_discount_usd`, `resolve_code`, `ResolvedDiscount`, `DiscountRejection` to the imports and `__all__`.

- [ ] **Step 5: Run the tests, lint, commit**

```bash
cd apps/api && uv run pytest tests/integration/ -q -k "affiliate or order" && uv run ruff check --fix src tests && uv run ruff format src tests
```

Commit with a message explaining that the server re-validates rather than trusting the preview.

---

### Task 4: Bind the buyer to the partner when the order is paid

**Files:**

- Create: `apps/api/src/yupay/modules/affiliate/attribution.py`
- Modify: `apps/api/src/yupay/modules/affiliate/api.py`
- Modify: `apps/api/src/yupay/modules/payments/service.py` (`_mark_payment_succeeded` and `_settle_late_payment`)
- Test: `apps/api/tests/integration/test_affiliate_discount.py`

**Interfaces:**

- Produces: `bind_attribution(db: AsyncSession, *, order: Order) -> bool`

Attribution is created at payment, not at order creation: an abandoned cart must not bind a buyer to a partner who sold them nothing. `UNIQUE(user_id)` makes the write race-safe without a lock — a loser hits the constraint and returns `False`.

- [ ] **Step 1: Write the failing tests**

Cover: an order with a code and a signed-in buyer binds; a second paid coded order for the same buyer does not create a second attribution; an order with no code binds nothing; a guest order binds nothing.

- [ ] **Step 2: Write the module**

```python
async def bind_attribution(db: AsyncSession, *, order: Order) -> bool:
    """Bind the buyer to the code's partner, if this is their first time.

    Called from the transaction that marks a catalog order paid. Returns
    ``False`` — never raises — when there is nothing to do or when a concurrent
    payment won the race, so a payment webhook can never fail because of the
    affiliate program.
    """
```

Implementation: return `False` unless `order.user_id` and `order.affiliate_code_id` are both set and `order.purpose == "catalog"`; look up the code for its `partner_id`; insert inside `db.begin_nested()` and return `False` on `IntegrityError`.

- [ ] **Step 3: Call it from both catalog payment paths**

In `_mark_payment_succeeded`, inside the `order.status == "pending_payment"` branch after `order.paid_at = moment`, and in `_settle_late_payment` after its `order.paid_at` assignment:

```python
    await affiliate_api.bind_attribution(db, order=order)
```

Import `from yupay.modules.affiliate import api as affiliate_api` at module top. Confirm no import cycle: `affiliate.api` mounts no router today, so `payments.service → affiliate.api → orders.models, wallet.service` is acyclic. **If a router is added to `affiliate.api` in Task 5, re-check this import** — that is exactly how step 1's circular import appeared.

- [ ] **Step 4: Run the tests, lint, commit**

---

### Task 5: The preview endpoint

**Files:**

- Create: `apps/api/src/yupay/modules/affiliate/schemas.py`
- Create: `apps/api/src/yupay/modules/affiliate/routes.py`
- Modify: `apps/api/src/yupay/api/v1/__init__.py`
- Test: `apps/api/tests/integration/test_affiliate_routes.py`

**Interfaces:**

- `POST /api/v1/affiliate/preview` with `{code, items: [{sku_id, qty, amount_usd?}], currency}` returning either `{applicable: true, code, percent, total_before, total_after, discount}` or `{applicable: false, reason: <DiscountRejection>}`.

**Rate limiting is required, not optional.** This endpoint tells the world whether a string is a usable promo code, so it is a guessing surface. Apply the existing per-route limit and the Redis-backed `ip_guard`; follow how `auth`'s credential endpoints wire it.

**Task 5 note on the import cycle:** adding `routes.py` and exporting a router from `api.py` recreates exactly the condition that broke step 1 — `payments.service` imports `affiliate.api`, and if that facade starts importing a router which imports `api/v1/deps`, the cycle closes. Either keep the router **out** of `api.py` (import it directly in `api/v1/__init__.py` from `affiliate.routes`), or have `payments.service` import `affiliate.attribution` directly. Prefer the first. Add a test that imports `yupay.modules.affiliate.attribution` in a fresh interpreter to catch a regression:

```bash
cd apps/api && uv run python -c "import yupay.modules.affiliate.attribution"
```

- [ ] **Step 1–5:** failing test → schemas → routes → mount → rate limit → green → commit.

---

### Task 6: Make the margin reports honest

**Files:**

- Modify: `apps/api/src/yupay/modules/orders/revenue.py`
- Test: `apps/api/tests/integration/test_affiliate_discount.py`

**This is the task the whole feature's reporting correctness rests on.**

- [ ] **Step 1: Write the failing test**

Create a delivered order with a known cost and a known discount, then assert through `stats.service` that reported revenue and margin are both **net of the discount**, and that `revenue − margin == cost` still holds.

- [ ] **Step 2: Subtract the discount in both expressions**

In `charged_usd_expr()`, every branch becomes `... - func.coalesce(OrderItem.discount_usd, 0)`. In `margin_usd_expr()`, likewise.

Both, not one. `margin_usd_expr` is computed independently of `charged_usd_expr`, and the invariant is `gross − margin == cost`. A discount lowers revenue and margin by the same amount and leaves cost alone, so subtracting in only one place would overstate margin by exactly the discount — the bug this whole task exists to prevent.

Update the module docstring in `revenue.py` to state the new invariant.

- [ ] **Step 3: Run the full stats and orders test suites**

Run: `cd apps/api && uv run pytest tests/ -q -k "stats or revenue or analytics or order"`
Expected: no failures. Any existing assertion about margin now has a discount term of zero, so nothing should move.

- [ ] **Step 4: Regenerate the API schema and client**

```bash
make gen-api
```

Then `npx prettier --check .` on tracked files and commit the regenerated `docs/api/openapi.json` and `packages/api-client/` alongside.

- [ ] **Step 5: Commit**

---

## Definition of Done for this plan

- [ ] Full backend suite green (`cd apps/api && uv run pytest -q` — about 9 minutes).
- [ ] Coverage of `yupay/modules/affiliate/*` ≥ 95%.
- [ ] `ruff check` and `ruff format --check` clean; `mypy src` no worse than baseline.
- [ ] `npx prettier --check .` clean on git-tracked files.
- [ ] Migration round-trips down and up against the dev database.
- [ ] `make gen-api` run; no OpenAPI drift.
- [ ] `docs/architecture/module-map.md` edges updated (`affiliate → payments` is new).
- [ ] The affiliate README's Money table updated: the discount is still not a posting, but the order columns are now real.
- [ ] Nothing pushed or deployed.

## Not in this plan

Steps 3–7: the checkout promo field on web and Mini App, partner authentication and the panel API, `apps/partners`, admin screens, infrastructure.
