"""``mailbox_key``: the inbox an address delivers to."""

from __future__ import annotations

import pytest
from yupay.modules.auth.mailbox import mailbox_key


@pytest.mark.parametrize(
    ("email", "key"),
    [
        ("Ab@Gmail.com", "ab@gmail.com"),
        ("a.b+b1234@gmail.com", "ab@gmail.com"),
        ("a.b@googlemail.com", "ab@gmail.com"),
        ("a.b+x@outlook.com", "a.b@outlook.com"),
        ("plain@yandex.ru", "plain@yandex.ru"),
    ],
)
def test_mailbox_key(email: str, key: str) -> None:
    assert mailbox_key(email) == key
