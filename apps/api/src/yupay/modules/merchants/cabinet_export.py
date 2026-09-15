"""CSV exports: the deposit statement, and the wholesale price list.

Both are built from the **same readers** the screens use — `transactions.build`
for the ledger, `price_list.build` for the catalog — rather than from queries
of their own. A statement that disagreed with the Транзакции screen about what
a merchant spent is worse than no statement, and the only reliable way to keep
two views of money identical is to give them one source.

Neither takes a window. A deposit ledger is one row per order plus the
occasional credit, and a price list is a few hundred SKUs, so both fit; the
bound below exists so that neither can ever become an unbounded read, not
because anybody is near it.
"""

from __future__ import annotations

import csv
import io
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from yupay.modules.merchants import price_list, transactions
from yupay.modules.merchants.models import Merchant

#: Ledger rows one export will read, newest first. The filename names the
#: range actually covered, so a truncated file says so by its own dates
#: rather than by a comment line that would break a CSV parser.
MAX_ROWS: Final = 10_000

#: One page of the shared reader per round trip.
_PAGE: Final = 200

#: Characters Excel and LibreOffice treat as the start of a **formula**. A
#: reseller's own ``merchant_order_id`` is free text from their system, and
#: this file is opened by their accountant, so a leading ``=`` would execute
#: there. The mitigation is OWASP's: prefix with an apostrophe, which those
#: programs strip on display and every other reader shows verbatim. Applied
#: only to the free-text columns — never to money or dates, which are
#: machine-formatted and which a stray apostrophe would make unparseable.
_FORMULA_LEAD: Final = ("=", "+", "-", "@", "\t", "\r")


def _text(value: str | None) -> str:
    """Free text, made safe to open in a spreadsheet."""
    if not value:
        return ""
    return f"'{value}" if value.startswith(_FORMULA_LEAD) else value


def _render(header: list[str], rows: list[list[str]]) -> str:
    buffer = io.StringIO()
    # ``\r\n`` per RFC 4180 — Excel on Windows is the reader that cares.
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


async def statement_csv(db: AsyncSession, *, merchant_id: str) -> tuple[str, str]:
    """The deposit ledger as CSV, newest first.

    Args:
        db: Session. The caller owns the transaction.
        merchant_id: Taken from the signed-in operator.

    Returns:
        ``(csv_text, filename)``. The filename carries the date range the file
        actually covers, so a run that hit :data:`MAX_ROWS` is self-describing.
    """
    rows: list[list[str]] = []
    cursor: str | None = None
    while len(rows) < MAX_ROWS:
        page = await transactions.build(db, merchant_id=merchant_id, limit=_PAGE, cursor=cursor)
        for item in page.items:
            rows.append(
                [
                    item.created_at.isoformat(),
                    item.kind,
                    str(item.amount_usd),
                    _text(item.merchant_order_id),
                    item.order_id or "",
                    item.transaction_id,
                ]
            )
        cursor = page.next_cursor
        # ``build`` only hands back a cursor on a full page, so an empty one
        # with a cursor cannot happen — and if it ever could, this loop would
        # spin forever rather than fail. Cheap insurance against that.
        if cursor is None or not page.items:
            break

    header = ["created_at", "kind", "amount_usd", "merchant_order_id", "order_id", "transaction_id"]
    span = f"{rows[-1][0][:10]}_{rows[0][0][:10]}" if rows else "empty"
    return _render(header, rows[:MAX_ROWS]), f"yupay-statement-{span}.csv"


async def price_list_csv(db: AsyncSession, *, merchant: Merchant) -> tuple[str, str]:
    """The wholesale price list as CSV — one row per orderable SKU.

    The same tree `GET /catalog` returns and the catalog page renders, so the
    export cannot advertise a price the order path would refuse.

    Args:
        db: Session. The caller owns the transaction.
        merchant: The signed-in operator's company; prices are theirs.

    Returns:
        ``(csv_text, filename)``.
    """
    catalog = await price_list.build(db, merchant=merchant)
    rows = [
        [
            sku.sku_id,
            _text(sku.sku_code),
            _text(brand.name),
            _text(product.name),
            sku.kind,
            _text(sku.unit),
            str(sku.price_usd or ""),
            str(sku.unit_price_usd or ""),
            str(sku.retail_price_usd or ""),
            str(sku.min_qty or ""),
            str(sku.max_qty or ""),
            str(sku.min_amount_usd or ""),
            str(sku.max_amount_usd or ""),
        ]
        for brand in catalog.brands
        for product in brand.products
        for sku in product.skus
    ]
    header = [
        "sku_id",
        "sku_code",
        "brand",
        "product",
        "kind",
        "unit",
        "price_usd",
        "unit_price_usd",
        "retail_price_usd",
        "min_qty",
        "max_qty",
        "min_amount_usd",
        "max_amount_usd",
    ]
    return _render(header, rows), "yupay-price-list.csv"


__all__ = ["MAX_ROWS", "price_list_csv", "statement_csv"]
