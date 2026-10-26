"""Response shapes for ``GET /merchant/cabinet/stats`` — the Statistics screen."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from yupay.modules.merchants.machine_schemas import UsdAmount

Granularity = Literal["hour", "day", "month"]


class CabinetStatsTotalsOut(BaseModel):
    """Counts and money for every order placed in a window."""

    orders: int
    delivered: int
    failed: int
    #: Neither delivered nor failed yet — paid, fulfilling, or waiting.
    in_flight: int
    #: Cancelled or refunded by a decision rather than by a delivery outcome.
    cancelled: int
    #: Charges minus every refund booked against these orders, from the ledger —
    #: the same rule as the dashboard's ``spend_usd``.
    spend_usd: UsdAmount
    refunded_usd: UsdAmount
    #: The mean net cost of the orders that cost anything — a failed order that
    #: came back in full would otherwise drag the average check down.
    avg_order_usd: UsdAmount


class CabinetStatsPointOut(BaseModel):
    """One bucket of the chart, gaps filled with zeros."""

    #: Start of the bucket in the caller's zone, as an aware ISO timestamp.
    at: datetime
    orders: int
    delivered: int
    failed: int
    spend_usd: UsdAmount


class CabinetStatsBrandOut(BaseModel):
    """One brand's share of the window."""

    brand_name: str | None
    logo_url: str | None
    orders: int
    delivered: int
    failed: int
    spend_usd: UsdAmount


class CabinetStatsSkuOut(BaseModel):
    """One pack's share of the window."""

    brand_name: str | None
    logo_url: str | None
    sku_name: str | None
    sku_code: str
    orders: int
    failed: int
    spend_usd: UsdAmount


class CabinetStatsOut(BaseModel):
    """Everything the Statistics screen draws for one window."""

    #: Echoed back; ``None`` for «all time». For «all time» the chart starts at
    #: the first order instead.
    since: datetime | None
    until: datetime
    granularity: Granularity
    totals: CabinetStatsTotalsOut
    #: The same-length window just before this one, for the «vs. before»
    #: arrows. ``None`` for «all time», which has nothing before it.
    previous: CabinetStatsTotalsOut | None
    series: list[CabinetStatsPointOut]
    brands: list[CabinetStatsBrandOut]
    skus: list[CabinetStatsSkuOut]
    #: Orders placed through ``/merchant/v1`` against those placed from the
    #: cabinet's catalog page (``manual-…`` ids).
    api_orders: int
    cabinet_orders: int
