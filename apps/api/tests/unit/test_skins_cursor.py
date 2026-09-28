import pytest
from yupay.core.errors import ValidationError
from yupay.modules.skins.service import decode_cursor, encode_cursor


def test_cursor_round_trips_value_and_id() -> None:
    token = encode_cursor(27867, "01a0e6aa-0000-7000-8000-000000000001")
    assert decode_cursor(token) == (27867, "01a0e6aa-0000-7000-8000-000000000001")


def test_cursor_round_trips_none_value_for_unpriced_rows() -> None:
    assert decode_cursor(encode_cursor(None, "x")) == (None, "x")


def test_garbage_cursor_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        decode_cursor("not-a-cursor")
