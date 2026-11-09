"""The machine-credential lifecycle: issue, list, revoke a merchant API key.

Three ordinary row operations on ``merchant_api_keys``, split out of
``service.py`` (Task 5) so the module's three concerns each have a file:
``service.py`` is the merchant account, ``deposit.py`` is its money, and this
is the credential a reseller's server signs with.

It is a better home than ``service.py`` was for a second reason. The machine
credential now has three files that own one stage each and nothing else:

- ``signing.py`` — the wire format (key ids, secrets, the canonical string);
- this module — the lifecycle (mint, list, revoke);
- ``auth.py`` — verification, as a FastAPI dependency.

``auth`` cannot be re-exported from ``api`` (it binds to the ``/api/v1``
dependency stack and the facade import would close a cycle); these three are
plain functions and are exported normally.

The secret is stored **encrypted**, not hashed — see ``signing``'s docstring
and the module README: an HMAC cannot be verified without the key material,
so hashing it would either forbid HMAC or make the digest itself the signing
key, which is key material in the clear under a reassuring name.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core import crypto
from yupay.core.clock import now
from yupay.core.errors import NotFoundError
from yupay.core.ids import new_id
from yupay.modules.merchants import signing
from yupay.modules.merchants.models import Merchant, MerchantApiKey
from yupay.modules.merchants.service import get_merchant


@dataclass(frozen=True)
class IssuedApiKey:
    """A freshly minted credential: the stored row plus the one-time API key.

    ``api_key`` (``ypk_…``, ADR-0103) exists in the clear only in this object
    and in the HTTP response that carries it. It is never logged and never
    returned again — the row keeps its secret half encrypted (``core.crypto``),
    which is what lets us check a bearer key and sign webhooks with it.
    """

    key: MerchantApiKey
    api_key: str


async def create_api_key(
    db: AsyncSession,
    *,
    merchant_id: str,
    label: str = "",
) -> IssuedApiKey:
    """Issue a single-value ``ypk_`` key for ``/merchant/v1``.

    Several live keys per merchant are supported on purpose (spec §9.2):
    rotation is "issue the new one, deploy it, revoke the old one", which has
    no downtime window. Nothing here revokes anything. The IP allowlist is the
    merchant's (``Merchant.api_ip_allowlist``), not the key's.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Who the key belongs to. Must exist.
        label: Operator-facing note, e.g. ``"prod server"``. Trimmed.

    Returns:
        The new row plus the plaintext key, which the caller must return to
        the operator immediately and then forget.

    Raises:
        NotFoundError: If no merchant with that id exists.
    """
    await get_merchant(db, merchant_id)
    key_id, secret = signing.new_api_key()
    secret_enc, secret_nonce = crypto.encrypt(secret, purpose=crypto.PURPOSE_MERCHANT_API_KEY)
    key = MerchantApiKey(
        id=new_id(),
        merchant_id=merchant_id,
        key_id=key_id,
        secret_enc=secret_enc,
        secret_nonce=secret_nonce,
        label=label.strip(),
        ip_allowlist=None,
    )
    db.add(key)
    await db.flush()
    # Pick up ``created_at``'s server default so the caller can render the row
    # without a round-trip of its own.
    await db.refresh(key)
    return IssuedApiKey(key=key, api_key=key_id + secret)


async def set_ip_allowlist(
    db: AsyncSession, *, merchant_id: str, entries: list[str] | None
) -> Merchant:
    """Replace the merchant's API IP allowlist; ``None`` or ``[]`` turns it off.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The merchant. Must exist.
        entries: Already validated by ``allowlist.normalize_allowlist``.

    Returns:
        The merchant row; ``api_ip_allowlist`` is ``None`` when the filter is off.

    Raises:
        NotFoundError: If no merchant with that id exists.
    """
    merchant = await get_merchant(db, merchant_id)
    merchant.api_ip_allowlist = entries or None
    await db.flush()
    return merchant


async def list_api_keys(db: AsyncSession, *, merchant_id: str) -> list[MerchantApiKey]:
    """Every key ever issued to a merchant, newest first, revoked ones included.

    Revoked keys stay listed: "which credential was live when this happened"
    is the question the cabinet's security page exists to answer.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Whose keys to list. Must exist.

    Returns:
        The rows, newest first.

    Raises:
        NotFoundError: If no merchant with that id exists — an empty list for
            a typo'd id must be a 404, not a plausible-looking ``[]``.
    """
    await get_merchant(db, merchant_id)
    stmt = (
        select(MerchantApiKey)
        .where(MerchantApiKey.merchant_id == merchant_id)
        # ``created_at`` is transaction-start time, so two keys minted in one
        # transaction tie; the UUIDv7 id is the monotonic tiebreak.
        .order_by(MerchantApiKey.created_at.desc(), MerchantApiKey.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def revoke_api_key(db: AsyncSession, *, merchant_id: str, key_id: str) -> MerchantApiKey:
    """Revoke a key. Idempotent: a second call leaves the first timestamp alone.

    The key is matched on ``(merchant_id, key_id)`` rather than ``key_id``
    alone, so one merchant's id in the path can never revoke another's
    credential.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The owning merchant. Must exist.
        key_id: The public half of the credential to revoke.

    Returns:
        The row, with ``revoked_at`` set.

    Raises:
        NotFoundError: If the merchant does not exist, or the key does not
            belong to it.
    """
    await get_merchant(db, merchant_id)
    key = (
        await db.execute(
            select(MerchantApiKey).where(
                MerchantApiKey.merchant_id == merchant_id,
                MerchantApiKey.key_id == key_id,
            )
        )
    ).scalar_one_or_none()
    if key is None:
        raise NotFoundError("api key not found")
    if key.revoked_at is None:
        key.revoked_at = now()
        await db.flush()
    return key


__all__ = [
    "IssuedApiKey",
    "create_api_key",
    "list_api_keys",
    "revoke_api_key",
    "set_ip_allowlist",
]
