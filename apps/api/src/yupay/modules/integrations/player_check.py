"""Storefront player-id verification (G2B nickname lookup / Waxpeer Steam
login check).

Advisory: for a ``g2b``-checked field, resolves the product's G2B
``game_code`` from its supplier mapping and proxies ``games_check_player``.
For a ``waxpeer``-checked field, proxies ``WaxpeerClient.validate_login`` —
Steam has no game_code/mapping to resolve, the login itself is the lookup
key. Either way the result carries the same three-way ``status``
(``valid``/``invalid``/``error``); faults degrade to ``status="error"`` so the
storefront never hits an error boundary. See ADR-0031.
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

    from yupay.modules.fulfillment.suppliers.waxpeer import WaxpeerFulfiller

logger = get_logger("yupay.integrations.player_check")

_CACHE_TTL_SECONDS = 300

_KNOWN_PROVIDERS = ("g2b", "waxpeer")


def _checkable_provider(required_fields: list[dict[str, Any]]) -> str | None:
    """The ``check.provider`` of the product's first checkable field, if any."""
    for f in required_fields:
        if isinstance(f, dict) and isinstance(f.get("check"), dict):
            provider = f["check"].get("provider")
            if provider in _KNOWN_PROVIDERS:
                return str(provider)
    return None


def product_is_checkable(required_fields: list[dict[str, Any]]) -> bool:
    """True when any form field opts into a supported (g2b or waxpeer) player check."""
    return _checkable_provider(required_fields) is not None


def _map_response(resp: dict[str, Any]) -> PlayerCheckOut:
    """Map a successful G2B ``checkPlayerId`` body to a public result.

    A 200 response with ``valid == "valid"`` is a real hit; any other body
    (``"invalid"``, empty, unexpected) means the supplier answered but the id
    does not resolve — that is the customer's mistake, so ``status="invalid"``,
    NOT ``"error"`` (which is reserved for our/supplier faults).
    """
    if str(resp.get("valid") or "").lower() == "valid":
        return PlayerCheckOut(status="valid", name=str(resp["name"]) if resp.get("name") else None)
    return PlayerCheckOut(status="invalid")


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
    """Redis key for a cached g2b player-check result.

    ``player_id`` is hashed (never stored raw) so the key carries no PII —
    it would otherwise be plaintext-visible via ``MONITOR``/``SCAN`` (§9).
    ``_hash_short`` is deterministic, so identical inputs still cache-hit.
    """
    return f"playercheck:g2b:{game_code}:{server_id or '-'}:{_hash_short(player_id)}"


def _waxpeer_cache_key(steam_login: str) -> str:
    """Redis key for a cached Steam-login check result.

    Same PII rule as :func:`_cache_key`: ``steam_login`` is personal data and
    is hashed, never stored raw, in the key. A distinct ``waxpeer:`` prefix
    keeps this namespace from ever colliding with a g2b ``player_id`` cache
    entry even if the raw strings happened to match.
    """
    return f"playercheck:waxpeer:{_hash_short(steam_login)}"


async def _check_waxpeer_login(
    fulfiller: WaxpeerFulfiller | None, *, steam_login: str
) -> PlayerCheckOut:
    """Validate a Steam login via ``WaxpeerClient.validate_login``.

    Same three-way contract as the g2b path: Waxpeer says the login is
    supported -> ``status="valid"`` (Steam has no display name, so ``name``
    stays ``None``); Waxpeer answers but the login isn't supported ->
    ``status="invalid"`` (the customer's mistake, not a fault); anything else
    (unconfigured, network/API failure) -> ``status="error"``, never raised.
    """
    redis = get_redis()
    key = _waxpeer_cache_key(steam_login)
    try:
        cached = await redis.get(key)
    except Exception:  # noqa: BLE001 — cache is best-effort
        cached = None
    if cached:
        return PlayerCheckOut.model_validate_json(cached)

    if fulfiller is None:
        return PlayerCheckOut(status="error")

    try:
        valid, _reason = await fulfiller._client().validate_login(steam_login)
    except Exception as exc:  # noqa: BLE001 — advisory; degrade, never 500
        logger.warning(
            "player_check_failed",
            provider="waxpeer",
            player_id_hash=_hash_short(steam_login),
            error=str(exc)[:200],
        )
        return PlayerCheckOut(status="error")

    out = PlayerCheckOut(status="valid") if valid else PlayerCheckOut(status="invalid")
    with contextlib.suppress(Exception):  # cache is best-effort
        await redis.set(key, out.model_dump_json(), ex=_CACHE_TTL_SECONDS)
    logger.info(
        "player_check",
        provider="waxpeer",
        player_id_hash=_hash_short(steam_login),
        status=out.status,
    )
    return out


async def check_player_for_product(
    session: AsyncSession,
    *,
    product_id: str,
    player_id: str,
    server_id: str | None,
) -> PlayerCheckOut:
    """Verify a player id (or Steam login) for a product. Never raises on
    upstream failure — folds it into ``status="error"``.

    A malformed (non-UUID) ``product_id`` is treated as "not found" rather
    than propagating the driver's ``DBAPIError`` — see ADR-0031: unknown
    product -> 404, and this endpoint never 5xx's.
    """
    from yupay.modules.integrations.routes import (
        _g2b_fulfiller_or_none,
        _waxpeer_fulfiller_or_none,
    )

    try:
        uuid.UUID(product_id)
    except ValueError as exc:
        raise NotFoundError("product not found") from exc

    product = await session.get(Product, product_id)
    if product is None:
        raise NotFoundError("product not found")
    provider = _checkable_provider(list(product.required_fields or []))
    if provider is None:
        raise ValidationError("product is not checkable")

    if provider == "waxpeer":
        return await _check_waxpeer_login(_waxpeer_fulfiller_or_none(), steam_login=player_id)

    game_code = await resolve_g2b_game_code(session, product_id)
    if game_code is None:
        return PlayerCheckOut(status="error")

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
        return PlayerCheckOut(status="error")

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
        return PlayerCheckOut(status="error")

    out = _map_response(resp)
    with contextlib.suppress(Exception):  # cache is best-effort
        await redis.set(key, out.model_dump_json(), ex=_CACHE_TTL_SECONDS)
    logger.info(
        "player_check",
        game_code=game_code,
        player_id_hash=_hash_short(player_id),
        status=out.status,
    )
    return out
