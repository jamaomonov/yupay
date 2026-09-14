"""A blank ``delivery_email`` must not cost the sale.

`canPay` on the web checkout read `(user !== null || emailOk)`, so for anyone
signed in the address was never validated — and the body carried
`delivery_email: ""`, which `EmailStr` rejects. The buyer saw «Buyurtma
yaratilmadi» and had no way out: the field seeds from the account, and **410 of
606 accounts on prod have no address on file** because Telegram and Steam hand
us none.

Measured on prod 2026-09-14: web checkout failed 36 times on 09-13 against 61
orders, where the month before ran near one in ten. The mini app, which never
sends the field, did not fail once.

The client is fixed to omit the key. This pins the server half, which exists
because a browser holding a cached bundle keeps sending what it was built to
send — a fix that lives only in the new JavaScript leaves every already-loaded
page failing until the cache turns over.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from yupay.modules.orders.schemas import OrderCreate

_BASE: dict[str, object] = {
    "currency": "UZS",
    "items": [{"sku_id": "019f6b61-d2c5-7ed3-a8c6-e1f84343d918", "qty": 1}],
}


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_delivery_email_is_read_as_no_address(blank: str) -> None:
    """Not "a malformed address" — "they did not give one"."""
    order = OrderCreate.model_validate({**_BASE, "delivery_email": blank})

    assert order.delivery_email is None


def test_an_address_that_is_given_is_still_kept() -> None:
    order = OrderCreate.model_validate({**_BASE, "delivery_email": "buyer@example.com"})

    assert order.delivery_email == "buyer@example.com"


def test_a_typo_is_still_refused() -> None:
    """Blank is a choice; malformed is a mistake, and worth saying so.

    The leniency is for the absence of an address, not for a wrong one — a
    buyer who typed something meant to be mailed, and silently dropping it
    would be the bug this file exists about, in the other direction.
    """
    with pytest.raises(ValidationError) as exc:
        OrderCreate.model_validate({**_BASE, "delivery_email": "not-an-address"})

    assert exc.value.errors()[0]["loc"] == ("delivery_email",)


def test_a_guests_blank_email_still_fails_on_its_own_field() -> None:
    """``guest_email`` is identity, not convenience, and is deliberately strict.

    Blanking it would trade a clear "that is not an address" for a confusing
    "actor must be exactly one of", and there is no sale to save either way: a
    guest without an address cannot be sent anything at all.
    """
    with pytest.raises(ValidationError) as exc:
        OrderCreate.model_validate({**_BASE, "guest_email": ""})

    assert exc.value.errors()[0]["loc"] == ("guest_email",)
