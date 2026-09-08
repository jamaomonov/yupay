"""The reseller's own deposit ledger — ``GET /merchant/v1/transactions``.

One page of the calling merchant's deposit movements, newest first: what we
credited, what each order spent, and (from M3) what came back. The signed
``amount_usd`` column adds up to the balance ``GET /merchant/v1/me`` reports,
which is the property that makes this a statement rather than a log.

## One query, not a second one

The grouped ledger sum is ``deposit.list_deposit_transactions`` — M1's, written
for the admin panel and *shared*, not copied. A second normal-side-signed sum
over the same postings would be a second chance to get a direction backwards,
and the two surfaces disagreeing about a merchant's ledger is the kind of bug
that is discovered by an invoice.

A bounded second statement maps the page's ``order`` references back to each
reseller's own ``merchant_order_id`` — one ``IN`` over at most ``limit`` ids,
never one query per row. Which rows carry one is ``deposit.order_reference_of``
and not a literal here: since M3b Task 2 an order charge is not the only
movement that names an order — a settlement credit may too — and a second
spelling of the reference type is what made ``refunded_usd`` read ``"0.00"``
forever in the first place.

## Why keyset paging and not OFFSET

This ledger is written *while it is read*: a merchant pulling their statement
is exactly the merchant placing orders, and every order appends a row at the
**head** of a newest-first list.

With ``OFFSET``, one insertion between page 1 and page 2 shifts every row down
one, so page 2 re-serves the last row of page 1 — and one deletion would skip a
row instead. Both happen silently: no error, no gap in the response, just a
statement that double-counts a charge.

A keyset cursor anchors on the last row of the page you were given —
``(created_at, transaction_id)``, the exact tuple the listing orders by, and
unique because ``id`` is the primary key. "Older than that row" is a fact about
the data, not a count of rows, so no insertion or deletion can move it. Rows
that land *after* your walk begins are simply newer than where you started,
which is the correct answer for a newest-first statement: you saw the ledger as
of the first page, and the next poll picks them up.

**Say exactly what that buys, because it is not "exactly once under every
interleaving".** ``WalletTransaction.created_at`` is
``server_default CURRENT_TIMESTAMP``, which in Postgres is *transaction start*,
not commit. So a transaction that began before your page was served and commits
after it can insert a row whose key sorts *inside* a range you have already
walked past, and you will not see it on this pass. The guarantee here is
**exactly-once against insertions at the head**, which is every ordinary write
to this ledger — an order charge commits in milliseconds — and it is strictly
better than OFFSET, which has the same commit-time blind spot *plus* shifts
under head insertions. Anything stronger needs a commit-order sequence
(``pg_current_snapshot``, or a monotonic counter assigned at commit), which
nothing in this ledger has and which a statement API does not need: a poller
comes back.

The cursor is opaque and carries no capability: it is a position, and the
merchant scope is applied separately from the signed identity, so a cursor
lifted from another merchant's page selects a timestamp and reveals nothing.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sqlalchemy import select

from yupay.core.errors import ValidationError
from yupay.modules.merchants import deposit
from yupay.modules.merchants.machine_schemas import (
    MerchantTransactionOut,
    MerchantTransactionsOut,
)
from yupay.modules.orders.models import Order

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

#: RFC 7807 ``code`` for a cursor we cannot read. Its own code rather than a
#: bare 422 because it is the one parameter a client constructs from our own
#: output: telling them *which* input was wrong is the difference between a
#: one-line fix and a support ticket.
CODE_INVALID_CURSOR: Final = "invalid_cursor"

#: Separates the two halves inside the encoded cursor. Not a character that can
#: appear in either an ISO-8601 timestamp or a UUID, so the split is exact.
_SEPARATOR: Final = "|"


def encode_cursor(created_at: datetime, transaction_id: str) -> str:
    """Encode a keyset position as an opaque, URL-safe token.

    Base64url without padding: the token travels in a query string, which is
    itself part of the signed canonical message, and ``=`` in a query value is
    legal but invites a client to re-encode it and break its own signature.

    Args:
        created_at: The anchor row's timestamp.
        transaction_id: The anchor row's id — the tiebreak that makes the
            pair unique.

    Returns:
        The token to hand back as ``next_cursor``.
    """
    raw = f"{created_at.isoformat()}{_SEPARATOR}{transaction_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _bad_cursor() -> ValidationError:
    """The one refusal :func:`decode_cursor` has. See its docstring for why one."""
    return ValidationError(
        "cursor is not one we issued; drop it and start from the newest page",
        code=CODE_INVALID_CURSOR,
    )


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Read a cursor back, or refuse it.

    Every failure mode is one 422 with one code. There is nothing to
    distinguish for a caller: the only correct source of a cursor is a
    ``next_cursor`` we sent, and anything else is the same mistake.

    **Both halves are validated, not just parsed**, because everything that
    survives this function is bound straight into a SQL comparison against a
    typed column. Decoding without checking is how a truncated cursor — a
    reseller's ``VARCHAR(88)`` column, a line-wrapped URL in a retry — reached
    ``uuid < $2`` as a non-UUID string and came back as a bare **500** from an
    endpoint whose published contract promises a recoverable ``422``. Three
    checks earn their place:

    - the id half must be a UUID, and the **canonical** form of it is what is
      returned: ``UUID()`` also accepts ``{braced}``, ``urn:uuid:`` and
      undashed spellings, and passing those through unchanged would parse here
      and still fail in Postgres, which is the same bug one layer down;
    - the timestamp must be timezone-aware, because ``created_at`` is
      ``timestamptz`` and every cursor we issue carries an offset — a naive one
      is not one we issued;
    - the separator must be present, so the two halves are really two.

    Args:
        cursor: The ``?cursor=`` value as sent.

    Returns:
        The ``(created_at, transaction_id)`` anchor, the id in canonical form.

    Raises:
        ValidationError: ``invalid_cursor``.
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        stamp, separator, transaction_id = (
            base64.urlsafe_b64decode(padded).decode("utf-8").partition(_SEPARATOR)
        )
        if not separator or not transaction_id:
            raise _bad_cursor()
        anchor_at = datetime.fromisoformat(stamp)
        if anchor_at.tzinfo is None:
            raise _bad_cursor()
        return anchor_at, str(UUID(transaction_id))
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise _bad_cursor() from exc


async def _merchant_order_ids(
    db: AsyncSession, *, merchant_id: str, order_ids: set[str]
) -> dict[str, str]:
    """Map our order ids to the reseller's own, for the ids on this page.

    One statement bounded by the page size. A statement line a reseller cannot
    match to their own order number is a support ticket, and they key their
    records on ``merchant_order_id`` because our README tells them to.

    Scoped by ``merchant_id`` as well as by id. Redundant today — a reference
    on this merchant's deposit is necessarily their own order — and kept
    because "scoped by the authenticated identity" is the rule this endpoint
    exists to hold, not a conclusion to re-derive at each call site.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The authenticated merchant.
        order_ids: The order ids referenced by this page. May be empty.

    Returns:
        ``{order_id: merchant_order_id}`` for the rows that resolve.
    """
    if not order_ids:
        return {}
    stmt = select(Order.id, Order.idempotency_key).where(
        Order.merchant_id == merchant_id, Order.id.in_(order_ids)
    )
    return {
        order_id: merchant_order_id
        for order_id, merchant_order_id in (await db.execute(stmt)).all()
        if merchant_order_id is not None
    }


async def build(
    db: AsyncSession, *, merchant_id: str, limit: int, cursor: str | None = None
) -> MerchantTransactionsOut:
    """Build one page of a merchant's deposit ledger.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: The authenticated merchant — the only scope.
        limit: Page size, already bounded by the route.
        cursor: A ``next_cursor`` from a previous page, or ``None`` to start
            at the newest row.

    Returns:
        The page, with ``next_cursor`` set only when older rows remain.

    Raises:
        ValidationError: ``invalid_cursor``.
        NotFoundError: If the merchant does not exist — unreachable through
            the machine API, whose merchant is a row the auth dependency
            loaded.
    """
    before = decode_cursor(cursor) if cursor is not None else None
    # One extra row is the "is there a next page" probe: a cursor on a
    # full-but-final page costs every client one wasted round trip, and a
    # separate COUNT would cost us one on every page.
    rows = await deposit.list_deposit_transactions(
        db, merchant_id=merchant_id, limit=limit + 1, before=before
    )
    has_more = len(rows) > limit
    rows = rows[:limit]

    own_ids = await _merchant_order_ids(
        db,
        merchant_id=merchant_id,
        order_ids={oid for txn, _ in rows if (oid := deposit.order_reference_of(txn)) is not None},
    )
    items = [
        MerchantTransactionOut(
            transaction_id=txn.id,
            kind=txn.kind,
            amount_usd=amount,
            order_id=deposit.order_reference_of(txn),
            merchant_order_id=own_ids.get(deposit.order_reference_of(txn) or ""),
            created_at=txn.created_at,
        )
        for txn, amount in rows
    ]
    last = rows[-1][0] if rows and has_more else None
    return MerchantTransactionsOut(
        items=items,
        next_cursor=encode_cursor(last.created_at, last.id) if last is not None else None,
    )


__all__ = [
    "CODE_INVALID_CURSOR",
    "build",
    "decode_cursor",
    "encode_cursor",
]
