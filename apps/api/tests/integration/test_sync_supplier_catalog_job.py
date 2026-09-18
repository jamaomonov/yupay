"""The hourly ``sync_supplier_catalog`` job, exercised against all three
suppliers it now covers (Task 4 of the supplier-catalog-pickers branch).

Lives in ``apps/api/tests/integration`` rather than ``apps/scheduler/tests``
because it needs a real database — ``test_nova_reconcile.py`` and
``test_gengine_reconcile.py`` set the same precedent for their own jobs (see
their module docstrings for why: the job resolves its own session via
``get_session_factory()``, redirected here at the *job module* to the
truncated test container).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core import config as cfg
from yupay.modules.integrations.catalog_sync import run_catalog_sync as real_run_catalog_sync
from yupay.modules.integrations.models import SupplierCatalogCache
from yupay_scheduler.jobs import sync_supplier_catalog

# Import the app so every module is loaded before the job reaches for them —
# same reasoning as test_nova_reconcile.py / test_gengine_reconcile.py.
import yupay.main  # noqa: F401  isort:skip

pytestmark = pytest.mark.asyncio

G2B_BASE = "https://g2b.jobtest.test/v1"
NOVA_BASE = "https://nova.jobtest.test"
GENGINE_BASE = "https://gengine.jobtest.test/v2.1"


@pytest.fixture(autouse=True)
def _all_suppliers_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("G2B_API_KEY", "test-key")
    monkeypatch.setenv("G2B_BASE_URL", G2B_BASE)
    monkeypatch.setenv("NOVA_API_KEY", "test-key")
    monkeypatch.setenv("NOVA_BASE_URL", NOVA_BASE)
    monkeypatch.setenv("GENGINE_API_KEY", "test-key")
    monkeypatch.setenv("GENGINE_BASE_URL", GENGINE_BASE)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _job_session_factory(monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(sync_supplier_catalog, "get_session_factory", lambda: factory)


def _mock_g2b_ok() -> None:
    respx.get(f"{G2B_BASE}/products?page=1&limit=200").mock(
        return_value=httpx.Response(
            200, json={"products": [{"id": 1, "title": "PUBG UC Voucher", "unit_price": 1.5}]}
        )
    )
    respx.get(f"{G2B_BASE}/games").mock(
        return_value=httpx.Response(
            200, json={"games": [{"code": "pubg_mobile", "name": "PUBG Mobile"}]}
        )
    )


def _mock_nova_ok() -> None:
    respx.get(f"{NOVA_BASE}/api/v2/topups", params={"limit": "100"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [{"category_id": "mobile_legends_ru", "name": "Mobile Legends (RU)"}],
                "meta": {"total": 1, "limit": 100, "next_cursor": None, "has_more": False},
            },
        )
    )


def _mock_gengine_ok() -> None:
    respx.get(f"{GENGINE_BASE}/recharge/services").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "items": [
                    {
                        "id": 5,
                        "name": "Mobile Legends Bang Bang (Russia)",
                        "type": "fixed",
                        "params": [],
                        "denominations": [],
                    }
                ],
            },
        )
    )


async def _cached_external_ids(db: AsyncSession, *, supplier_slug: str, kind: str) -> set[str]:
    rows = (
        (
            await db.execute(
                select(SupplierCatalogCache.external_id).where(
                    SupplierCatalogCache.supplier_slug == supplier_slug,
                    SupplierCatalogCache.kind == kind,
                )
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


@respx.mock
async def test_a_supplier_http_failure_does_not_stop_the_others(db_session: AsyncSession) -> None:
    """NOVA's upstream 500s; G2B and G-Engine still get synced in the same
    tick — the per-supplier sync's own best-effort handling, exercised
    through the real job."""
    _mock_g2b_ok()
    _mock_gengine_ok()
    respx.get(f"{NOVA_BASE}/api/v2/topups", params={"limit": "100"}).mock(
        return_value=httpx.Response(500, text="boom")
    )

    await sync_supplier_catalog.run_sync_supplier_catalog()

    assert await _cached_external_ids(db_session, supplier_slug="g2b", kind="voucher") == {"1"}
    assert await _cached_external_ids(db_session, supplier_slug="gengine", kind="game") == {"5"}
    assert await _cached_external_ids(db_session, supplier_slug="nova", kind="game") == set()


@respx.mock
async def test_a_supplier_sync_that_raises_does_not_stop_the_others(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defense in depth: even if a per-supplier sync broke its own
    best-effort contract and raised outright, the job's own per-supplier
    ``try``/``except`` must still let the rest of the tick complete.

    ``g2b`` is the one that raises here, not ``nova``. ``_SUPPLIERS`` sorts
    to ``(g2b, gengine, nova)``, so nova is always *last* — a regression
    that replaced the job's ``continue`` with a ``break`` (stopping the
    whole tick on the first failure instead of skipping just that
    supplier) would still leave every other supplier synced whenever the
    failing one happens to be last, because there'd be nothing left to
    iterate to anyway. Both tests in this module used to fail nova
    exclusively, so that regression could pass them both. Failing the
    *first* supplier in iteration order instead means a stray ``break``
    really would cost gengine and nova their tick — verified by making
    that exact swap in the job and watching this test fail before writing
    it this way.
    """
    _mock_nova_ok()
    _mock_gengine_ok()

    async def _flaky(db: Any, *, supplier_slug: str) -> Any:
        if supplier_slug == "g2b":
            raise RuntimeError("simulated crash mid-sync")
        return await real_run_catalog_sync(db, supplier_slug=supplier_slug)

    monkeypatch.setattr(sync_supplier_catalog, "run_catalog_sync", _flaky)

    await sync_supplier_catalog.run_sync_supplier_catalog()

    assert await _cached_external_ids(db_session, supplier_slug="gengine", kind="game") == {"5"}
    assert await _cached_external_ids(db_session, supplier_slug="nova", kind="game") == {
        "mobile_legends_ru"
    }
