"""The buyer's view of a skin trade (plan 3a, Task 8)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from yupay.core.ids import new_id
from yupay.modules.skins.models import SkinTrade
from yupay.modules.skins.trade_view import skin_trade_out

SEND_UNTIL = datetime(2026, 9, 29, 12, 30, tzinfo=UTC)
RELEASE = datetime(2026, 10, 5, 16, 0, tzinfo=UTC)


def _row(**over: object) -> SkinTrade:
    row = SkinTrade(
        id=new_id(),
        order_item_id=new_id(),
        project_id="p",
        listing_id=1,
        market_hash_name="AK-47 | Redline (Field-Tested)",
        paid_units=1,
        status=None,
        is_released=False,
        seller={},
    )
    for k, v in over.items():
        setattr(row, k, v)
    return row


@pytest.mark.parametrize(
    ("over", "state"),
    [
        ({"status": 0}, "buying"),
        ({"status": 2, "trade_id": "9"}, "buying"),
        ({"status": 4, "trade_id": "9", "send_until": SEND_UNTIL}, "offer_sent"),
        ({"status": 4, "trade_id": "9", "release_date": RELEASE}, "accepted"),
        ({"status": 5, "trade_id": "9", "release_date": RELEASE, "is_released": True}, "released"),
        ({"status": 6, "reason": "Buyer failed to accept"}, "failed"),
    ],
)
def test_each_waxpeer_status_reads_as_one_state(over: dict[str, object], state: str) -> None:
    assert skin_trade_out(_row(**over), fulfillment_state="in_progress").state == state


def test_an_offer_carries_its_link_deadline_and_seller() -> None:
    out = skin_trade_out(
        _row(
            status=4,
            trade_id="9393511289",
            send_until=SEND_UNTIL,
            seller={"name": "darpan6awx", "avatar_url": None, "level": 12, "joined_at": None},
        ),
        fulfillment_state="in_progress",
    )
    assert out.offer_url == "https://steamcommunity.com/tradeoffer/9393511289/"
    assert out.send_until == SEND_UNTIL
    assert out.seller is not None
    assert out.seller.name == "darpan6awx"


def test_a_declined_offer_says_not_accepted() -> None:
    out = skin_trade_out(
        _row(status=6, reason="Buyer failed to accept"), fulfillment_state="failed"
    )
    assert (out.state, out.reason_code) == ("failed", "not_accepted")


def test_a_line_that_never_bought_and_failed_was_sold_out() -> None:
    out = skin_trade_out(_row(status=None), fulfillment_state="failed")
    assert (out.state, out.reason_code) == ("failed", "sold_out")
