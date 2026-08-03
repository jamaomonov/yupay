from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core import config as cfg
from yupay.modules.payments import provider_state as ps

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _acquirer_env(monkeypatch: pytest.MonkeyPatch):
    # Make Payme + Uzum config-available so they appear in the list.
    monkeypatch.setenv("PAYME_MERCHANT_ID", "m")
    monkeypatch.setenv("PAYME_KEY", "k")
    monkeypatch.setenv("UZUM_SERVICE_ID", "1")
    monkeypatch.setenv("UZUM_LOGIN", "l")
    monkeypatch.setenv("UZUM_PASSWORD", "p")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


async def test_providers_hides_disabled_and_flags_maintenance(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await ps.set_logical_state(db_session, provider="payme", state="disabled", changed_by=None)
    await ps.set_logical_state(db_session, provider="uzum", state="maintenance", changed_by=None)
    await db_session.commit()

    r = await integration_client.get("/api/v1/payments/providers")
    assert r.status_code == 200
    by_slug = {p["slug"]: p["status"] for p in r.json()["providers"]}
    assert "payme" not in by_slug  # disabled → hidden
    assert by_slug.get("uzum") == "maintenance"
