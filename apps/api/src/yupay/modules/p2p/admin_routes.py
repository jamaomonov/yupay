"""Admin routes for P2P top-ups: the router, and the switch row.

Cards live in ``admin_cards``, the journal and reservations in ``admin_journal``;
both are included here under the same prefix and admin guard.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from yupay.core.clock import now
from yupay.core.errors import ValidationError
from yupay.core.idempotency import normalize_idempotency_key
from yupay.core.logging import get_logger
from yupay.modules.admin.deps import require_admin
from yupay.modules.merchants.models import Merchant
from yupay.modules.merchants.route_replay import IdempotencyKeyHeader, remember, replayed
from yupay.modules.p2p import admin_cards, admin_journal
from yupay.modules.p2p.admin_deps import Admin, Db, parse_uuid
from yupay.modules.p2p.models import P2PSettings
from yupay.modules.p2p.schemas import P2PSettingsIn, P2PSettingsOut
from yupay.modules.p2p.settings import load_settings

router = APIRouter(
    prefix="/admin/p2p",
    tags=["admin:p2p"],
    dependencies=[Depends(require_admin)],
)

log = get_logger("yupay.p2p.admin")


def _settings_out(s: object) -> P2PSettingsOut:
    return P2PSettingsOut.model_validate(s, from_attributes=True)


@router.get("/settings", response_model=P2PSettingsOut, summary="P2P switches")
async def get_p2p_settings(db: Db) -> P2PSettingsOut:
    """Current mode, allowlist and the HUMO bot's Telegram id."""
    out = _settings_out(await load_settings(db))
    await db.commit()  # load_settings creates the row on a fresh database
    return out


def _set_owner(s: P2PSettings, owner: int | None) -> None:
    """Store the owner's Telegram id; a different owner unpins the old connection.

    The pinned Business connection belongs to whoever was the owner when it was
    captured. Keeping it after the owner changes would keep trusting the
    previous account; the new owner reconnects the bot to pin theirs.
    """
    if owner != s.owner_telegram_user_id and s.business_connection_id is not None:
        s.business_connection_id = None
        log.info("p2p.connection_unpinned", reason="owner_changed")  # no ids: personal data
    s.owner_telegram_user_id = owner


@router.patch("/settings", response_model=P2PSettingsOut, summary="Change P2P switches")
async def patch_p2p_settings(
    body: P2PSettingsIn, db: Db, admin: Admin, idempotency_key: IdempotencyKeyHeader = None
) -> P2PSettingsOut:
    """Apply the fields present in the body; ``null`` clears either Telegram id."""
    key = normalize_idempotency_key(idempotency_key)
    if (hit := await replayed(db, scope="p2p.settings", key=key, model=P2PSettingsOut)) is not None:
        return hit
    s = await load_settings(db)
    sent = body.model_fields_set
    if body.mode is not None:
        s.mode = body.mode
    if body.allowlist_merchant_ids is not None:
        ids = list(dict.fromkeys(body.allowlist_merchant_ids))
        bad = [i for i in ids if parse_uuid(i) is None]
        ids = [i for i in ids if parse_uuid(i) is not None]
        known = set(
            (await db.execute(select(Merchant.id).where(Merchant.id.in_(ids)))).scalars().all()
        )
        if unknown := bad + [i for i in ids if i not in known]:
            raise ValidationError(
                "unknown merchant in allowlist", code="p2p_unknown_merchant", merchant_ids=unknown
            )
        s.allowlist_merchant_ids = ids
    if "humo_bot_user_id" in sent:
        s.humo_bot_user_id = body.humo_bot_user_id
    if "owner_telegram_user_id" in sent:
        _set_owner(s, body.owner_telegram_user_id)
    s.updated_by = admin.id
    s.updated_at = now()
    await db.flush()
    out = _settings_out(s)
    # Field names only: the Telegram ids are personal data.
    log.info(
        "p2p.settings_saved",
        admin_id=admin.id,
        changed=sorted(sent),
        mode=s.mode,
        allowlist_size=len(s.allowlist_merchant_ids),
    )
    await remember(db, scope="p2p.settings", key=key, body=out.model_dump(mode="json"))
    await db.commit()
    return out


router.include_router(admin_cards.router)
router.include_router(admin_journal.router)


__all__ = ["router"]
