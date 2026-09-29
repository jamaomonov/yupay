"""The bot's message when a skin purchase fell through and the money went to the balance."""

from __future__ import annotations

from yupay.modules.notifications.service import skin_refund_text


def test_it_names_the_skin_and_where_the_money_is() -> None:
    text = skin_refund_text(name="AK-47 | Slate (Battle-Scarred)", amount="40 000 сум")
    assert "AK-47 | Slate (Battle-Scarred)" in text
    assert "40 000 сум" in text
    assert "баланс YuPay" in text
    assert "несколько минут" not in text


def test_a_supplier_shortfall_asks_to_try_again_later() -> None:
    text = skin_refund_text(name="AK-47 | Slate", amount="40 000 сум", try_later=True)
    assert "несколько минут" in text


def test_the_name_is_escaped_for_html() -> None:
    assert "&lt;b&gt;" in skin_refund_text(name="<b>x</b>", amount="1 сум")


def test_the_paid_note_promises_a_code_only_for_codes() -> None:
    from yupay.modules.notifications.service import paid_note

    assert "код" in paid_note(kinds={"voucher"}, skin=False)
    assert "код" not in paid_note(kinds={"top_up"}, skin=False)
    assert "зачислен" in paid_note(kinds={"top_up"}, skin=False)
    skin = paid_note(kinds={"top_up"}, skin=True)
    assert "Steam" in skin
    assert "код" not in skin
    assert "код" not in paid_note(kinds={"top_up", "voucher"}, skin=False)
