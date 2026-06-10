"""Recovery paths that swallow ``IntegrityError`` must not destroy the caller's
transaction.

``ensure_account`` / ``post`` (wallet), ``handle_webhook`` dedup (payments) and
``bulk_upload`` (inventory) all recover from a unique-constraint conflict. The
recovery has to roll back **only the conflicting insert** (SAVEPOINT), never the
whole request-scoped session — otherwise previously flushed work (order status,
payment rows, audit attempts) silently evaporates while the caller carries on.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Importing payments.service directly (outside the app) trips the
# service ← api.v1 ← wallet.routes import cycle; loading the router package
# first resolves it the same way ``bootstrap.create_app`` does.
import yupay.api.v1  # noqa: F401  isort: skip
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)
from yupay.modules.inventory import service as inv_svc
from yupay.modules.inventory.models import InventoryCode
from yupay.modules.payments import service as payments_svc
from yupay.modules.payments.models import PaymentWebhook
from yupay.modules.wallet import service as wallet_svc
from yupay.modules.wallet.models import WalletAccount
from yupay.modules.wallet.service import Leg

pytestmark = pytest.mark.asyncio


async def test_ensure_account_race_preserves_outer_transaction(
    db_engine, db_session: AsyncSession
) -> None:
    """A lost ``ensure_account`` race must not erase earlier flushed work."""
    prior = await wallet_svc.ensure_account(
        db_session, owner_type="user", owner_id="u1", kind="user_cashback", currency="USD"
    )

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as other:
        rival = WalletAccount(
            id=new_id(), owner_type="user", owner_id="u1", kind="user_wallet", currency="USD"
        )
        other.add(rival)
        await other.flush()  # uncommitted insert holds the unique-index lock

        task = asyncio.create_task(
            wallet_svc.ensure_account(
                db_session, owner_type="user", owner_id="u1", kind="user_wallet", currency="USD"
            )
        )
        await asyncio.sleep(0.3)  # let the task reach the blocked INSERT
        await other.commit()  # unblocks the task with IntegrityError
        account = await task

    assert account.id == rival.id

    still_there = (
        await db_session.execute(select(WalletAccount).where(WalletAccount.id == prior.id))
    ).scalar_one_or_none()
    assert still_there is not None, "earlier flushed work was wiped by a full rollback"


async def test_post_replay_race_preserves_outer_transaction(
    db_engine, db_session: AsyncSession
) -> None:
    """A lost ``post`` idempotency race returns the rival txn without nuking the session."""
    acc_user = await wallet_svc.ensure_account(
        db_session, owner_type="user", owner_id="u2", kind="user_wallet", currency="USD"
    )
    acc_house = await wallet_svc.ensure_account(
        db_session, owner_type="house", owner_id="house", kind="house_promo_expense", currency="USD"
    )
    await db_session.commit()

    def legs() -> list[Leg]:
        return [
            Leg(account_id=acc_user.id, direction="D", amount=Decimal("5"), currency="USD"),
            Leg(account_id=acc_house.id, direction="C", amount=Decimal("5"), currency="USD"),
        ]

    marker = await wallet_svc.ensure_account(
        db_session, owner_type="user", owner_id="u2", kind="user_promo_credit", currency="USD"
    )

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as other:
        rival_txn = await wallet_svc.post(
            other, kind="admin.adjust", legs=legs(), idempotency_key="race-key", actor="test"
        )
        task = asyncio.create_task(
            wallet_svc.post(
                db_session,
                kind="admin.adjust",
                legs=legs(),
                idempotency_key="race-key",
                actor="test",
            )
        )
        await asyncio.sleep(0.3)
        await other.commit()
        txn = await task

    assert txn.id == rival_txn.id

    still_there = (
        await db_session.execute(select(WalletAccount).where(WalletAccount.id == marker.id))
    ).scalar_one_or_none()
    assert still_there is not None, "earlier flushed work was wiped by a full rollback"


async def test_duplicate_webhook_preserves_outer_transaction(db_session: AsyncSession) -> None:
    """A replayed webhook deduplicates without rolling back the caller's session."""
    db_session.add(
        PaymentWebhook(
            id=new_id(),
            provider="mock",
            external_event_id="evt-dup",
            payload={},
            signature_ok=True,
        )
    )
    await db_session.commit()

    marker = await wallet_svc.ensure_account(
        db_session, owner_type="user", owner_id="u3", kind="user_wallet", currency="USD"
    )

    body = json.dumps({"event_id": "evt-dup", "payment_id": "p-x", "outcome": "succeeded"}).encode(
        "utf-8"
    )
    result = await payments_svc.handle_webhook(db_session, provider="mock", headers={}, body=body)
    assert result is None

    still_there = (
        await db_session.execute(select(WalletAccount).where(WalletAccount.id == marker.id))
    ).scalar_one_or_none()
    assert still_there is not None, "earlier flushed work was wiped by a full rollback"


@pytest.fixture
async def _seed_sku(db_session: AsyncSession) -> str:
    category = Category(
        id=new_id(),
        slug="vouchers",
        sort_order=10,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Ваучеры")],
    )
    brand = Brand(
        id=new_id(),
        slug="netflix",
        category_id=category.id,
        sort_order=10,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Netflix")],
    )
    product = Product(
        id=new_id(),
        slug="netflix-gift",
        brand_id=brand.id,
        kind="voucher",
        sort_order=10,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Gift card")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="netflix-10-us",
        denomination="10",
        region="US",
        price_usd=Decimal("1.00"),
        sort_order=10,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return sku.id


async def test_bulk_upload_mid_batch_duplicate_keeps_earlier_inserts(
    db_session: AsyncSession, _seed_sku: str
) -> None:
    """A duplicate mid-batch must not roll back codes already inserted in the batch."""
    await inv_svc.bulk_upload(db_session, sku_id=_seed_sku, codes=["AAA-1"], uploaded_by="t")
    await db_session.commit()

    result = await inv_svc.bulk_upload(
        db_session, sku_id=_seed_sku, codes=["BBB-1", "AAA-1", "CCC-1"], uploaded_by="t"
    )
    await db_session.commit()

    assert result.succeeded == 2
    assert result.duplicates == 1

    count = (
        await db_session.execute(
            select(func.count()).select_from(InventoryCode).where(InventoryCode.sku_id == _seed_sku)
        )
    ).scalar_one()
    assert count == 3, "a code inserted earlier in the batch was wiped by a full rollback"
