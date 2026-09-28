"""Load and persist the pricing document: Redis -> ``skin_pricing_rules`` row 1 -> defaults.

Same contract as ``gifts.settings``: a save touches Postgres only and the
caller publishes to Redis after its own commit. The document is validated
through :class:`PricingRules` on both sides, so a hand-edited row that no
longer parses falls back to ``DEFAULT_RULES`` with a warning rather than
pricing the catalogue off garbage.
"""

from __future__ import annotations

import contextlib
import json

from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.clock import now
from yupay.core.config import Settings
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.skins.models import SkinPricingRules
from yupay.modules.skins.pricing import DEFAULT_RULES, PricingRules
from yupay.modules.skins.taxonomy import CATEGORY_SLUGS

log = get_logger("yupay.skins.settings")

_RULES_KEY = "skins:pricing"
_RULES_TTL_SECONDS = 3600


def _parse(raw: object) -> PricingRules | None:
    try:
        if isinstance(raw, bytes | str):
            return PricingRules.model_validate_json(raw)
        return PricingRules.model_validate(raw)
    except (ValidationError, ValueError):
        return None


async def load_rules(db: AsyncSession, *, fresh: bool = False) -> PricingRules:
    """The live rules. A Redis error or a bad cached document falls through to Postgres.

    Args:
        db: The session to read row 1 with.
        fresh: Skip the Redis copy. A repricing writer holding
            ``repricing.lock_pricing`` passes it: Redis is published only after
            an admin's commit, so right after one it can still hold the old rules.
    """
    redis = get_redis()
    if not fresh:
        with contextlib.suppress(RedisError):
            cached = await redis.get(_RULES_KEY)
            parsed = _parse(cached) if cached is not None else None
            if parsed is not None:
                return parsed
    row = await db.get(SkinPricingRules, 1)
    rules = _parse(row.rules) if row is not None else None
    if row is not None and rules is None:
        log.warning("skins.pricing.row_invalid", reason="falling back to DEFAULT_RULES")
    rules = rules or DEFAULT_RULES
    with contextlib.suppress(RedisError):
        await redis.set(_RULES_KEY, rules.model_dump_json(), ex=_RULES_TTL_SECONDS)
    return rules


async def save_rules(db: AsyncSession, *, rules: PricingRules, admin_id: str) -> None:
    """Upsert row 1. Postgres only — publish after commit."""
    document = json.loads(rules.model_dump_json())
    row = await db.get(SkinPricingRules, 1)
    if row is None:
        db.add(SkinPricingRules(id=1, rules=document, updated_by=admin_id))
    else:
        row.rules = document
        row.updated_by = admin_id
        row.updated_at = now()
    await db.flush()


async def publish_rules(rules: PricingRules) -> None:
    """Push a committed document into Redis. Call only after ``db.commit()``."""
    await get_redis().set(_RULES_KEY, rules.model_dump_json(), ex=_RULES_TTL_SECONDS)


def enabled_categories(settings: Settings) -> list[str]:
    """``cs2_skins_categories`` parsed, deduped, unknown slugs dropped, order kept."""
    out: list[str] = []
    for raw in settings.cs2_skins_categories.split(","):
        slug = raw.strip().lower()
        if slug in CATEGORY_SLUGS and slug not in out:
            out.append(slug)
    return out


__all__ = ["enabled_categories", "load_rules", "publish_rules", "save_rules"]
