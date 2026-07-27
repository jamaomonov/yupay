"""``FormField.pattern`` write-time ReDoS guard.

``pattern`` is admin-authored and later run inline (``re.fullmatch``, no
timeout) against untrusted customer input in
``yupay.modules.orders.validation``. ``FormField`` is shared between the
storefront read DTOs (``schemas.py``) and the admin write DTOs
(``admin_schemas.py`` imports ``FormField`` directly), so a validator here
guards both directions.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError
from yupay.modules.catalog.schemas import FormField


def _base_field(**extra: object) -> dict[str, object]:
    return {"key": "player_id", "label": {"ru": "ID"}, "type": "text", **extra}


@pytest.mark.parametrize(
    "pattern",
    [
        "^[0-9]{6,20}$",
        "^[A-Za-z0-9_-]{3,64}$",
        r"^[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}$",
        "(ab)+$",
        "^(foo|bar)$",
    ],
)
def test_legit_pattern_accepted(pattern: str) -> None:
    field = FormField.model_validate(_base_field(pattern=pattern))
    assert field.pattern == pattern


def test_field_without_pattern_is_fine() -> None:
    field = FormField.model_validate(_base_field())
    assert field.pattern is None


@pytest.mark.parametrize(
    "pattern",
    [
        "(a+)+",
        "(a*)*",
        "(a+)*$",
        r"(\d+\s*)+",
        "(a+){2,}",
    ],
)
def test_nested_quantifier_rejected(pattern: str) -> None:
    with pytest.raises(PydanticValidationError, match="nested quantifier"):
        FormField.model_validate(_base_field(pattern=pattern))


def test_huge_bounded_repetition_rejected() -> None:
    with pytest.raises(PydanticValidationError, match="bounded repetition"):
        FormField.model_validate(_base_field(pattern="a{1001,2000}"))


def test_overlong_pattern_rejected() -> None:
    with pytest.raises(PydanticValidationError, match="too long"):
        FormField.model_validate(_base_field(pattern="a" * 300))


def test_too_many_quantifiers_rejected() -> None:
    with pytest.raises(PydanticValidationError, match="quantifiers"):
        FormField.model_validate(_base_field(pattern="(a+)" * 25))


def test_invalid_regex_rejected() -> None:
    with pytest.raises(PydanticValidationError, match="valid regular expression"):
        FormField.model_validate(_base_field(pattern="(unclosed"))
