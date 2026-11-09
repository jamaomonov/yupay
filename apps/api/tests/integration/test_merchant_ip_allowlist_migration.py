"""Migration 0109: per-key IP allowlists folded into one list per merchant (ADR-0103).

The backfill decides, for every integrated reseller on production, whether its
API keeps working the moment the new image starts — so each of its three rules
runs here against rows inserted at 0108:

* every live key restricted → the union of their entries;
* every live key unrestricted → no filter;
* a mix → no filter (restricting would lock the open key out);

and a revoked key's list is never carried over.

``db_engine`` is requested for fixture ordering (testcontainer up, schema at
head, tables truncated). The ``finally`` returns this worker to head whatever
happens — see ``test_order_source_migration`` for why that matters.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from yupay.core import config as cfg
from yupay.core.ids import new_id

pytestmark = pytest.mark.asyncio

_PREVIOUS = "0108_brand_variants"


def _alembic_config() -> Config:
    api_dir = Path(__file__).resolve().parents[2]
    alembic_cfg = Config(str(api_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(api_dir / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", cfg.get_settings().database_url)
    return alembic_cfg


async def _sql(statement: str, **params: Any) -> list[Any]:
    engine = create_async_engine(cfg.get_settings().database_url, future=True)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(statement), params)
            return list(result.all()) if result.returns_rows else []
    finally:
        await engine.dispose()


async def _merchant(*keys: tuple[list[str] | None, bool]) -> str:
    """A merchant with ``(ip_allowlist, revoked)`` keys, inserted at 0108."""
    merchant_id = new_id()
    await _sql(
        "INSERT INTO merchants (id, title) VALUES (:id, :t)", id=merchant_id, t=merchant_id[:8]
    )
    for allowlist, revoked in keys:
        await _sql(
            "INSERT INTO merchant_api_keys (id, merchant_id, key_id, secret_enc, secret_nonce,"
            " ip_allowlist, revoked_at) VALUES (:id, :m, :k, '\\x00', '\\x00',"
            " CAST(CAST(:ips AS text) AS inet[]), CASE WHEN :revoked THEN now() END)",
            id=new_id(),
            m=merchant_id,
            k=f"ypm_{new_id()}",
            ips=None if allowlist is None else "{" + ",".join(allowlist) + "}",
            revoked=revoked,
        )
    return merchant_id


async def _allowlist(merchant_id: str) -> list[str] | None:
    rows = await _sql(
        "SELECT array(SELECT host(e) || CASE WHEN masklen(e) IN (32, 128) THEN ''"
        " ELSE '/' || masklen(e) END FROM unnest(api_ip_allowlist) e) AS ips,"
        " api_ip_allowlist IS NULL AS off FROM merchants WHERE id = :id",
        id=merchant_id,
    )
    ips, off = rows[0]
    return None if off else sorted(ips)


async def test_the_backfill_follows_the_three_rules(db_engine: Any) -> None:
    alembic_cfg = _alembic_config()
    try:
        await asyncio.to_thread(command.downgrade, alembic_cfg, _PREVIOUS)
        same = await _merchant((["203.0.113.5"], False), (["203.0.113.5"], False))
        several = await _merchant(
            (["176.9.111.172"], False),
            (["142.132.250.229"], False),
            (["116.202.193.233", "2a01:4f8:241:10c9::/64"], False),
            (["10.0.0.0/8"], True),  # revoked: not carried over
        )
        open_ = await _merchant((None, False), (None, False))
        mixed = await _merchant((None, False), (["170.168.6.54"], False))
        no_keys = await _merchant()

        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

        assert await _allowlist(same) == ["203.0.113.5"]
        assert await _allowlist(several) == sorted(
            ["176.9.111.172", "142.132.250.229", "116.202.193.233", "2a01:4f8:241:10c9::/64"]
        )
        assert await _allowlist(open_) is None
        assert await _allowlist(mixed) is None
        assert await _allowlist(no_keys) is None
    finally:
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
