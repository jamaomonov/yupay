"""Bulk sourcing-rule writes — the write side of the sourcing-by-brand screen.

Split out of ``service.py`` (already ~340 lines before this) the same way
``brand_overview.py`` was split out for the read side — this keeps both
under the module's 400-LOC soft limit and keeps ``service.py`` (the single
definition of ``set_rule``/``delete_rule``/the auto-routing rules) untouched.

The endpoint this backs lets an operator switch many SKUs of one brand onto
one supplier (or back to ``auto``) in a single request. **Partial success is
the point**: a 35-SKU brand where one SKU was force-onto a supplier with no
active mapping should still write the other 34 — an all-or-nothing batch
would tell the operator nothing about which row was wrong, and would force
them to retry the other 34 by hand. So each SKU is its own unit of work,
and a per-SKU failure is reported by name rather than aborting the batch.

**Why a savepoint per item.** The outer session belongs to the request (see
``core.db.get_session``): it commits once, after the route handler returns,
and rolls back everything if any exception escapes the handler. Today,
every failure this module actually produces — the "SKU not found" check and
``set_rule``'s validation guards — is raised from a plain ``SELECT``, before
any row for that SKU is touched, so the underlying Postgres transaction is
never put in a failed state by them and a bare ``try/except`` around
``set_rule`` would already leave prior successful flushes intact. But that is
an accident of what ``set_rule`` happens to validate before it writes today,
not a property this module can rely on: a future validation added *after* a
write (or any genuine DB-level error — a constraint violation, a
serialization failure) would abort the whole asyncpg transaction, and every
subsequent item — success or failure — would then fail with
"current transaction is aborted" without ever running. A ``SAVEPOINT`` per
item (``AsyncSession.begin_nested``) makes that robust instead of incidental:
on a per-item failure, only that item's savepoint is rolled back; every
earlier item's flush stays intact for the outer commit, and every later item
still runs normally.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.core.errors import NotFoundError, ValidationError
from yupay.modules.inventory import service as inv_svc
from yupay.modules.sourcing.schemas import MAX_BULK_SKU_IDS, SourcingBulkRuleResultOut
from yupay.modules.sourcing.service import Mode, delete_rule, get_rule, set_rule


async def bulk_set_rules(
    db: AsyncSession,
    *,
    sku_ids: list[str],
    mode: Mode,
    supplier_slug: str | None,
    admin_id: str,
) -> list[SourcingBulkRuleResultOut]:
    """Apply one sourcing decision to many SKUs, each its own unit of work.

    ``mode="auto"`` deletes each SKU's explicit rule, same as the single-SKU
    ``DELETE /admin/sourcing/rules/{sku_id}`` route — except a SKU that is
    already implicitly ``auto`` (no rule row) is reported as a success, not
    a "not found" failure: the desired end state already holds. Every other
    mode calls :func:`yupay.modules.sourcing.service.set_rule` unchanged —
    including its guard against forcing a mapping-required supplier
    (``MAPPING_REQUIRED_SUPPLIERS``, which includes every reserve supplier)
    onto a SKU with no active mapping for it.

    Args:
        db: Active session — one commit for the whole request, at the route
            layer, after this returns (``core.db.get_session``).
        sku_ids: Already capped at :data:`MAX_BULK_SKU_IDS` by the caller.
        mode: Same sourcing mode applied to every listed SKU.
        supplier_slug: Required (and validated) by ``set_rule`` for
            ``force_supplier``; ignored for every other mode.
        admin_id: Recorded on each written rule's ``updated_by``.

    Returns:
        One :class:`SourcingBulkRuleResultOut` per input SKU, in input order
        (duplicates included, each evaluated independently).

    Raises:
        ValidationError: ``len(sku_ids)`` exceeds :data:`MAX_BULK_SKU_IDS` —
            a whole-request rejection, not a per-item one: an oversized list
            is a malformed request, not 100 individual failures.
    """
    if len(sku_ids) > MAX_BULK_SKU_IDS:
        raise ValidationError(
            f"bulk sourcing update is capped at {MAX_BULK_SKU_IDS} SKUs per call",
            extra={"got": len(sku_ids), "max": MAX_BULK_SKU_IDS},
        )

    results: list[SourcingBulkRuleResultOut] = []
    for sku_id in sku_ids:
        try:
            async with db.begin_nested():
                await inv_svc.get_sku_or_404(db, sku_id)
                if mode == "auto":
                    if await get_rule(db, sku_id) is not None:
                        await delete_rule(db, sku_id)
                else:
                    await set_rule(
                        db,
                        sku_id=sku_id,
                        mode=mode,
                        supplier_slug=supplier_slug,
                        admin_id=admin_id,
                    )
        except (ValidationError, NotFoundError) as exc:
            results.append(SourcingBulkRuleResultOut(sku_id=sku_id, ok=False, error=exc.detail))
            continue
        results.append(SourcingBulkRuleResultOut(sku_id=sku_id, ok=True, error=None))
    return results


__all__ = ["bulk_set_rules"]
