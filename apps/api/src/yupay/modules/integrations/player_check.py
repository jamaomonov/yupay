"""Storefront player-id verification (G2B nickname lookup).

Advisory: resolves a product's G2B ``game_code`` from its supplier mapping and
proxies ``games_check_player``. Errors are folded into ``{valid: False, reason}``
so the storefront never hits an error boundary. See ADR-0031.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.catalog.models import Product, Sku
from yupay.modules.fulfillment.suppliers.g2b import _hash_short
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.schemas import PlayerCheckOut

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("yupay.integrations.player_check")

_CACHE_TTL_SECONDS = 300


def product_is_checkable(required_fields: list[dict[str, Any]]) -> bool:
    """True when any form field opts into a g2b player check."""
    return any(
        isinstance(f, dict) and isinstance(f.get("check"), dict)
        and f["check"].get("provider") == "g2b"
        for f in required_fields
    )


def _map_response(resp: dict[str, Any]) -> PlayerCheckOut:
    raw_valid = str(resp.get("valid") or "").lower()
    if raw_valid == "valid":
        return PlayerCheckOut(valid=True, name=str(resp["name"]) if resp.get("name") else None)
    return PlayerCheckOut(valid=False, reason=str(resp.get("message") or "rejected"))


async def resolve_g2b_game_code(session: AsyncSession, product_id: str) -> str | None:
    """The G2B game_code for a product = external_product_id of any active
    g2b game mapping among its SKUs. A product's game SKUs share one code."""
    stmt = (
        select(SkuSupplierMapping.external_product_id)
        .join(Sku, Sku.id == SkuSupplierMapping.sku_id)
        .where(
            Sku.product_id == product_id,
            SkuSupplierMapping.supplier_slug == "g2b",
            SkuSupplierMapping.kind == "game",
            SkuSupplierMapping.is_active.is_(True),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _cache_key(game_code: str, player_id: str, server_id: str | None) -> str:
    """Redis key for a cached player-check result.

    ``player_id`` is hashed (never stored raw) so the key carries no PII —
    it would otherwise be plaintext-visible via ``MONITOR``/``SCAN`` (§9).
    ``_hash_short`` is deterministic, so identical inputs still cache-hit.
    """
    return f"playercheck:g2b:{game_code}:{server_id or '-'}:{_hash_short(player_id)}"


async def check_player_for_product(
    session: AsyncSession,
    *,
    product_id: str,
    player_id: str,
    server_id: str | None,
) -> PlayerCheckOut:
    """Verify a player id for a product. Never raises on upstream failure —
    folds it into ``{valid: False, reason}``.

    A malformed (non-UUID) ``product_id`` is treated as "not found" rather
    than propagating the driver's ``DBAPIError`` — see ADR-0031: unknown
    product -> 404, and this endpoint never 5xx's.
    """
    from yupay.modules.integrations.routes import _g2b_fulfiller_or_none

    try:
        uuid.UUID(product_id)
    except ValueError as exc:
        raise NotFoundError("product not found") from exc

    product = await session.get(Product, product_id)
    if product is None:
        raise NotFoundError("product not found")
    if not product_is_checkable(list(product.required_fields or [])):
        raise ValidationError("product is not checkable")

    game_code = await resolve_g2b_game_code(session, product_id)
    if game_code is None:
        return PlayerCheckOut(valid=False, reason="unavailable")

    redis = get_redis()
    key = _cache_key(game_code, player_id, server_id)
    try:
        cached = await redis.get(key)
    except Exception:  # noqa: BLE001 — cache is best-effort
        cached = None
    if cached:
        return PlayerCheckOut.model_validate_json(cached)

    fulfiller = _g2b_fulfiller_or_none()
    if fulfiller is None:
        return PlayerCheckOut(valid=False, reason="unavailable")

    try:
        resp = await fulfiller._client().games_check_player(
            game_code=game_code, player_id=player_id, server_id=server_id, charname=None
        )
    except Exception as exc:  # noqa: BLE001 — advisory; degrade, never 500
        logger.warning(
            "player_check_failed",
            game_code=game_code,
            player_id_hash=_hash_short(player_id),
            error=str(exc)[:200],
        )
        return PlayerCheckOut(valid=False, reason="unavailable")

    out = _map_response(resp)
    with contextlib.suppress(Exception):  # cache is best-effort
        await redis.set(key, out.model_dump_json(), ex=_CACHE_TTL_SECONDS)
    logger.info(
        "player_check", game_code=game_code, player_id_hash=_hash_short(player_id),
        valid=out.valid,
    )
    return out
